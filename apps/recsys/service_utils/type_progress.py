from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from django.db.models import QuerySet

from apps.recsys.models import Attempt, TaskTag, TaskType, TypeMastery


@dataclass(frozen=True)
class TypeProgressInfo:
    raw_mastery: float
    effective_mastery: float
    coverage_ratio: float
    required_count: int
    covered_count: int
    required_tags: tuple[TaskTag, ...]
    covered_tag_ids: frozenset[int]


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

    solved_pairs = (
        Attempt.objects.filter(
            user=user,
            is_correct=True,
            task__type_id__in=type_ids,
            task__tags__isnull=False,
        )
        .values_list("task__type_id", "task__tags")
        .distinct()
    )

    covered_by_type: dict[int, set[int]] = defaultdict(set)
    for type_id, tag_id in solved_pairs:
        if tag_id is not None:
            covered_by_type[int(type_id)].add(int(tag_id))

    progress_map: dict[int, TypeProgressInfo] = {}
    for type_id in type_ids:
        required_tags = required_tags_map.get(type_id, ())
        required_ids = {tag.id for tag in required_tags}
        covered_ids = covered_by_type.get(type_id, set())
        covered_required_ids = required_ids.intersection(covered_ids)

        required_count = len(required_tags)
        covered_count = len(covered_required_ids)
        coverage_ratio = 1.0 if required_count == 0 else covered_count / required_count

        raw_mastery = mastery_by_type.get(type_id, 0.0)
        effective_mastery = min(raw_mastery, coverage_ratio)

        progress_map[type_id] = TypeProgressInfo(
            raw_mastery=raw_mastery,
            effective_mastery=effective_mastery,
            coverage_ratio=coverage_ratio,
            required_count=required_count,
            covered_count=covered_count,
            required_tags=required_tags,
            covered_tag_ids=frozenset(covered_required_ids),
        )

    return progress_map
