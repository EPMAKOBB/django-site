from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.db.models import Count, QuerySet

from apps.recsys.models import Attempt, Task, TaskTag, TaskType, TypeMastery
from apps.recsys.service_utils.publication import public_tasks_queryset


@dataclass(frozen=True)
class TagProgressInfo:
    tag: TaskTag
    solved_count: int
    total_count: int
    ratio: float
    coverage_ratio: float


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
    previous_year_evidence: int = 0


def _clamp_mastery(value: float) -> float:
    if value is None:
        return 0.0
    return max(0.0, min(1.0, float(value)))


def build_type_progress_map(
    *,
    user,
    task_type_ids: Iterable[int],
    as_of=None,
) -> dict[int, TypeProgressInfo]:
    """Return progress information per task type for the given ``user``.

    ``effective_mastery`` is the visible learning progress by required tags.
    For small tag banks, progress follows actual coverage. For larger banks,
    five correctly solved distinct tasks are enough to close the tag.
    ``coverage_ratio`` remains the raw published-bank coverage signal.
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

    from .exam_context import task_filter, grading_context
    tasks_per_type_tag = {}
    solved_by_type_tag = {}
    # A real task may be in several annual catalogs. Count evidence once per
    # task within a projection, never create extra Attempt records.
    banks = list(public_tasks_queryset(Task.objects.filter(task_filter(task_type_ids=type_ids)))
                 .distinct().select_related("type__answer_schema", "answer_schema")
                 .prefetch_related("tags", "placements__task_type__answer_schema", "placements__answer_schema"))
    successful_qs = Attempt.objects.filter(user=user, task_id__in=[t.pk for t in banks], is_correct=True, is_valid_attempt=True)
    if as_of:
        successful_qs = successful_qs.filter(created_at__lte=as_of)
    successful = list(successful_qs.values("pk", "task_id", "exam_version_id", "context_snapshot", "task_snapshot"))
    evidence = {}
    for row in successful:
        evidence.setdefault(row["task_id"], []).append(row)
    inherited_by_type = {}
    for task_type in task_types:
        required = {tag.pk for tag in required_tags_map[task_type.pk]}
        inherited = set()
        for task in banks:
            placements = list(task.placements.all())
            placement = next((p for p in placements if p.task_type_id == task_type.pk and p.status == "active"), None)
            if placement is None and (placements or task.type_id != task_type.pk):
                continue
            grading = grading_context(task, placement)
            compatible = []
            for row in evidence.get(task.pk, []):
                snapshot = row["task_snapshot"] or {}
                # Old partial data remains labelled inferred in history. Whenever
                # criteria were frozen, require the same criteria for full credit.
                if any(key in snapshot and snapshot[key] != grading[key] for key in ("max_score", "scoring_scheme", "answer_schema")):
                    continue
                if snapshot.get("type") == "static" and any(key in snapshot and snapshot[key] != getattr(task, key) for key in ("description", "correct_answer")):
                    continue
                compatible.append(row)
                if row["exam_version_id"] and row["exam_version_id"] != task_type.exam_version_id:
                    inherited.add(row["pk"])
            for tag_id in required.intersection(tag.pk for tag in task.tags.all()):
                key = (task_type.pk, tag_id)
                tasks_per_type_tag[key] = tasks_per_type_tag.get(key, 0) + 1
                if any(row["context_snapshot"].get("tag_ids") is None or tag_id in row["context_snapshot"]["tag_ids"] for row in compatible):
                    solved_by_type_tag[key] = solved_by_type_tag.get(key, 0) + 1
        inherited_by_type[task_type.pk] = len(inherited)

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
            coverage_ratio = 0.0
            if total_count > 0:
                coverage_ratio = min(1.0, solved_count / total_count)
            if coverage_ratio >= 1.0 and total_count > 0:
                covered_tag_ids.add(tag.id)
            ratio = _visible_tag_progress_ratio(
                solved_count=solved_count,
                total_count=total_count,
            )
            tag_progress_entries.append(
                TagProgressInfo(
                    tag=tag,
                    solved_count=solved_count,
                    total_count=total_count,
                    ratio=ratio,
                    coverage_ratio=coverage_ratio,
                )
            )

        if required_count == 0:
            coverage_ratio = 1.0
        else:
            coverage_ratio = (
                sum(entry.coverage_ratio for entry in tag_progress_entries) / required_count
            )

        raw_mastery = mastery_by_type.get(type_id, 0.0)
        if required_count == 0:
            effective_mastery = _clamp_mastery(raw_mastery)
        else:
            effective_mastery = (
                sum(entry.ratio for entry in tag_progress_entries) / required_count
            )

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
            previous_year_evidence=inherited_by_type.get(type_id, 0),
        )

    return progress_map


def _visible_tag_progress_ratio(*, solved_count: int, total_count: int) -> float:
    if total_count <= 0:
        return 0.0
    if total_count <= 5:
        return _clamp_mastery(solved_count / total_count)
    return _clamp_mastery(solved_count / 5)
