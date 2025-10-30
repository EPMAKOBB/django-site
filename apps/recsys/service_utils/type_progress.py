from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from django.db.models import Count, QuerySet

from apps.recsys.models import Attempt, Task, TaskTag, TaskType, TypeMastery


@dataclass(frozen=True)
class TagProgressInfo:
    tag: TaskTag
    solved_count: int
    total_count: int
    ratio: float


@dataclass(frozen=True)
class TypeProgressInfo:
    raw_mastery: float
    effective_mastery: float
    coverage_ratio: float
    required_count: int
    covered_count: int
    required_tags: tuple[TaskTag, ...]
    covered_tag_ids: frozenset[int]
    tag_progress: tuple[TagProgressInfo, ...]


def _clamp_mastery(value: float) -> float:
    if value is None:
        return 0.0
    return max(0.0, min(1.0, float(value)))


def build_type_progress_map(
    *,
    user,
    task_type_ids: Iterable[int],
) -> dict[int, TypeProgressInfo]:
    """Return progress information per task type for the given ``user``.

    The ``effective_mastery`` limits the raw mastery value by the coverage of
    required tags.  If no required tags are configured for a type, the coverage
    is treated as 1.0.
    """

    type_ids = list({int(type_id) for type_id in task_type_ids if type_id is not None})
    if not type_ids:
        return {}

    mastery_by_type: dict[int, float] = {
        tm.task_type_id: _clamp_mastery(tm.mastery)
        for tm in TypeMastery.objects.filter(user=user, task_type_id__in=type_ids)
    }

    task_types: QuerySet[TaskType] = TaskType.objects.filter(id__in=type_ids).prefetch_related(
        "required_tags"
    )
    required_tags_map: dict[int, tuple[TaskTag, ...]] = {
        task_type.id: tuple(task_type.required_tags.all()) for task_type in task_types
    }

    required_tag_ids: set[int] = {
        tag.id for tags in required_tags_map.values() for tag in tags
    }

    tasks_per_type_tag: dict[tuple[int, int], int] = {}
    if required_tag_ids:
        task_totals = (
            Task.objects.filter(
                type_id__in=type_ids,
                tags__in=required_tag_ids,
            )
            .values("type_id", "tags")
            .annotate(total=Count("id", distinct=True))
        )
        tasks_per_type_tag = {
            (int(row["type_id"]), int(row["tags"])): int(row["total"])
            for row in task_totals
        }

    solved_by_type_tag: dict[tuple[int, int], int] = {}
    if required_tag_ids:
        solved_rows = (
            Attempt.objects.filter(
                user=user,
                is_correct=True,
                task__type_id__in=type_ids,
                task__tags__in=required_tag_ids,
            )
            .values("task__type_id", "task__tags")
            .annotate(total=Count("task_id", distinct=True))
        )
        solved_by_type_tag = {
            (int(row["task__type_id"]), int(row["task__tags"])): int(row["total"])
            for row in solved_rows
        }

    progress_map: dict[int, TypeProgressInfo] = {}
    for type_id in type_ids:
        required_tags = required_tags_map.get(type_id, ())
        required_count = len(required_tags)
        tag_progress_entries: list[TagProgressInfo] = []
        covered_tag_ids: set[int] = set()

        for tag in required_tags:
            key = (type_id, tag.id)
            total_count = tasks_per_type_tag.get(key, 0)
            solved_count = solved_by_type_tag.get(key, 0)
            ratio = 0.0
            if total_count > 0:
                ratio = min(1.0, solved_count / total_count)
            if ratio >= 1.0 and total_count > 0:
                covered_tag_ids.add(tag.id)
            tag_progress_entries.append(
                TagProgressInfo(
                    tag=tag,
                    solved_count=solved_count,
                    total_count=total_count,
                    ratio=ratio,
                )
            )

        if required_count == 0:
            coverage_ratio = 1.0
        else:
            coverage_ratio = sum(entry.ratio for entry in tag_progress_entries) / required_count

        raw_mastery = mastery_by_type.get(type_id, 0.0)
        if required_count == 0:
            effective_mastery = _clamp_mastery(raw_mastery)
        else:
            effective_mastery = coverage_ratio

        covered_count = len(covered_tag_ids)

        progress_map[type_id] = TypeProgressInfo(
            raw_mastery=raw_mastery,
            effective_mastery=effective_mastery,
            coverage_ratio=coverage_ratio,
            required_count=required_count,
            covered_count=covered_count,
            required_tags=required_tags,
            covered_tag_ids=frozenset(covered_tag_ids),
            tag_progress=tuple(tag_progress_entries),
        )

    return progress_map
