from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import Attempt, RecommendationLog, SkillMastery, TagMastery, Task
from .service_utils.publication import public_tasks_queryset

ETA_SUCCESS = 5.0
TARGET_SUCCESS = 0.65
SIGMA_MATCH = 0.18
MU_FORGETTING_RISK = 0.05
SUCCESS_THRESHOLD = 0.7

B_WEAK = 0.35
B_COVERAGE = 0.25
B_MATCH = 0.25
B_SPACING = 0.10
B_DATA = 0.05
SOLVED_TASK_COOLDOWN = timedelta(days=14)


@dataclass(frozen=True)
class RecommendationCandidate:
    task: Task
    score: float
    score_snapshot: dict
    reason_snapshot: dict
    weak_tags_snapshot: list[dict]
    coverage_gain_snapshot: float
    spacing_gain_snapshot: float


def _clamp_unit(value: float | None) -> float:
    if value is None:
        return 0.0
    return max(0.0, min(1.0, float(value)))


def _normalised_difficulty(task: Task) -> float:
    raw = float(task.difficulty_level or 0.0)
    if raw > 1.0:
        raw = raw / 100.0
    return _clamp_unit(raw)


def _forgetting_risk(last_success_at, now) -> float:
    if last_success_at is None:
        return 0.0
    delta = now - last_success_at
    delta_days = max(0.0, delta.total_seconds() / 86400.0)
    return _clamp_unit(1.0 - math.exp(-MU_FORGETTING_RISK * delta_days))


def _weakness_components(mastery_value: float, coverage_value: float, forgetting_risk: float) -> dict:
    return {
        "mastery_gap": _clamp_unit(1.0 - mastery_value),
        "coverage_gap": _clamp_unit(1.0 - coverage_value),
        "forgetting_risk": _clamp_unit(forgetting_risk),
    }


def _weakness_value(components: dict) -> float:
    weakness = (
        0.5 * components["mastery_gap"]
        + 0.3 * components["coverage_gap"]
        + 0.2 * components["forgetting_risk"]
    )
    return _clamp_unit(weakness)


def _legacy_score(user, task: Task) -> float:
    total = 0.0
    count = 0
    for skill in task.skills.all():
        mastery = SkillMastery.objects.filter(user=user, skill=skill).first()
        if mastery:
            total += float(mastery.mastery or 0.0)
            count += 1
    avg_mastery = total / count if count else 0.0
    return 1.0 - _clamp_unit(avg_mastery)


def _legacy_candidate(user, task: Task) -> RecommendationCandidate:
    score = _legacy_score(user, task)
    score_snapshot = {
        "final_score": score,
        "mode": "legacy",
    }
    return RecommendationCandidate(
        task=task,
        score=score,
        score_snapshot=score_snapshot,
        reason_snapshot={
            "mode": "legacy",
            "summary": "Legacy skill-based fallback because the task has no tags.",
        },
        weak_tags_snapshot=[],
        coverage_gain_snapshot=0.0,
        spacing_gain_snapshot=0.0,
    )


def _mvp_candidate(user, task: Task, now) -> RecommendationCandidate:
    tag_records = list(task.tags.values("id", "name", "slug"))
    if not tag_records:
        return _legacy_candidate(user, task)

    tag_ids = [tag["id"] for tag in tag_records]
    tag_masteries = {
        mastery.task_tag_id: mastery
        for mastery in TagMastery.objects.filter(user=user, task_tag_id__in=tag_ids)
    }

    task_mastery_values: list[float] = []
    weak_values: list[float] = []
    coverage_gap_values: list[float] = []
    spacing_values: list[float] = []
    weak_tags_snapshot: list[dict] = []

    for tag in tag_records:
        mastery_obj = tag_masteries.get(tag["id"])
        if mastery_obj is None:
            mastery_value = 0.0
            coverage_value = 0.0
            forgetting_risk = 0.0
            components = {
                "mastery_gap": 1.0,
                "coverage_gap": 1.0,
                "forgetting_risk": 0.0,
            }
            weakness = 0.8
            confidence = 0.0
            stability = 0.0
            attempts_total = 0
        else:
            mastery_value = _clamp_unit(mastery_obj.mastery)
            coverage_value = _clamp_unit(mastery_obj.coverage)
            forgetting_risk = _forgetting_risk(mastery_obj.last_success_at, now)
            components = _weakness_components(
                mastery_value,
                coverage_value,
                forgetting_risk,
            )
            weakness = _weakness_value(components)
            confidence = _clamp_unit(mastery_obj.confidence)
            stability = _clamp_unit(mastery_obj.stability)
            attempts_total = int(mastery_obj.attempts_total or 0)

        task_mastery_values.append(mastery_value)
        weak_values.append(weakness)
        coverage_gap_values.append(1.0 - coverage_value)
        spacing_values.append(forgetting_risk)
        weak_tags_snapshot.append(
            {
                "tag_id": tag["id"],
                "tag_name": tag["name"],
                "tag_slug": tag["slug"],
                "mastery": mastery_value,
                "coverage": coverage_value,
                "confidence": confidence,
                "stability": stability,
                "attempts_total": attempts_total,
                "weakness": weakness,
                "mastery_gap": components["mastery_gap"],
                "coverage_gap": components["coverage_gap"],
                "forgetting_risk": components["forgetting_risk"],
            }
        )

    task_mastery = sum(task_mastery_values) / len(task_mastery_values)
    difficulty = _normalised_difficulty(task)
    predicted_success = 1.0 / (1.0 + math.exp(-ETA_SUCCESS * (task_mastery - difficulty)))
    match_score = math.exp(
        -((predicted_success - TARGET_SUCCESS) ** 2) / (2.0 * (SIGMA_MATCH ** 2))
    )
    weak_gain = sum(weak_values) / len(weak_values)
    coverage_gain = sum(coverage_gap_values) / len(coverage_gap_values)
    spacing_gain = sum(spacing_values) / len(spacing_values)
    data_bonus = 1.0 / (1.0 + int(task.attempts_total or 0))
    priority_manual = float(task.priority_manual or 1.0)

    base_score = (
        B_WEAK * weak_gain
        + B_COVERAGE * coverage_gain
        + B_MATCH * match_score
        + B_SPACING * spacing_gain
        + B_DATA * data_bonus
    )
    final_score = priority_manual * base_score

    weak_tags_snapshot.sort(key=lambda item: (item["weakness"], item["tag_id"]), reverse=True)
    score_snapshot = {
        "mode": "mvp",
        "final_score": final_score,
        "base_score": base_score,
        "priority_manual": priority_manual,
        "task_mastery": task_mastery,
        "difficulty_level": difficulty,
        "predicted_success": predicted_success,
        "target_success": TARGET_SUCCESS,
        "weak_gain": weak_gain,
        "coverage_gain": coverage_gain,
        "spacing_gain": spacing_gain,
        "match_score": match_score,
        "data_bonus": data_bonus,
        "weights": {
            "weak": B_WEAK,
            "coverage": B_COVERAGE,
            "match": B_MATCH,
            "spacing": B_SPACING,
            "data": B_DATA,
        },
    }
    reason_snapshot = {
        "mode": "mvp",
        "summary": "Ranked by weak-tag gain, coverage gap, spacing risk, success match, and task novelty.",
        "top_weak_tags": [
            {
                "tag_id": item["tag_id"],
                "tag_name": item["tag_name"],
                "weakness": item["weakness"],
            }
            for item in weak_tags_snapshot[:3]
        ],
    }
    return RecommendationCandidate(
        task=task,
        score=final_score,
        score_snapshot=score_snapshot,
        reason_snapshot=reason_snapshot,
        weak_tags_snapshot=weak_tags_snapshot,
        coverage_gain_snapshot=coverage_gain,
        spacing_gain_snapshot=spacing_gain,
    )


def _attempt_successful(attempt: Attempt) -> bool:
    if attempt.is_correct:
        return True
    max_score = int(attempt.max_score or attempt.task.get_max_score() or 1)
    if max_score <= 0:
        return False
    score = float(attempt.score or 0.0)
    return (score / max_score) >= SUCCESS_THRESHOLD


def _select_candidates(
    user,
    now,
    *,
    exam_version=None,
    task_type_ids: list[int] | tuple[int, ...] | None = None,
    exclude_recent: bool = True,
    exclude_solved: bool = True,
):
    queryset = public_tasks_queryset()
    if exam_version is not None:
        queryset = queryset.filter(exam_version=exam_version)
    if task_type_ids:
        queryset = queryset.filter(type_id__in=task_type_ids)
    if exclude_solved:
        solved_cutoff = now - SOLVED_TASK_COOLDOWN
        solved_task_ids = Attempt.objects.filter(
            user=user,
            is_valid_attempt=True,
            is_correct=True,
        ).filter(
            Q(checked_at__gte=solved_cutoff)
            | Q(checked_at__isnull=True, created_at__gte=solved_cutoff)
        ).values_list("task_id", flat=True)
        queryset = queryset.exclude(id__in=solved_task_ids)
    if exclude_recent:
        recent_task_ids = RecommendationLog.objects.filter(
            user=user,
            recommended_at__gte=now - timedelta(days=1),
        ).values_list("task_id", flat=True)
        queryset = queryset.exclude(id__in=recent_task_ids)
    return queryset


def _log_recommendations(user, candidates, *, source_mode: str, now) -> None:
    logs = []
    for index, candidate in enumerate(candidates, start=1):
        logs.append(
            RecommendationLog(
                user=user,
                task=candidate.task,
                status=RecommendationLog.Status.RECOMMENDED,
                recommended_at=now,
                source_mode=source_mode,
                rank_position=index,
                score_snapshot=candidate.score_snapshot,
                reason_snapshot=candidate.reason_snapshot,
                weak_tags_snapshot=candidate.weak_tags_snapshot,
                coverage_gain_snapshot=candidate.coverage_gain_snapshot,
                spacing_gain_snapshot=candidate.spacing_gain_snapshot,
                completed=False,
            )
        )
    RecommendationLog.objects.bulk_create(logs)


def mark_recommendation_opened(recommendation: RecommendationLog | None) -> RecommendationLog | None:
    if recommendation is None:
        return None
    if recommendation.status == RecommendationLog.Status.OPENED:
        return recommendation
    recommendation.status = RecommendationLog.Status.OPENED
    recommendation.save(update_fields=["status", "updated_at"])
    return recommendation


def mark_latest_recommendation_opened(
    user,
    task: Task,
    *,
    source_mode: str | None = None,
) -> RecommendationLog | None:
    queryset = RecommendationLog.objects.filter(user=user, task=task).order_by(
        "-recommended_at",
        "-created_at",
        "-id",
    )
    if source_mode:
        queryset = queryset.filter(source_mode=source_mode)
    recommendation = queryset.first()
    return mark_recommendation_opened(recommendation)


def attach_attempt_to_recommendation(attempt: Attempt) -> RecommendationLog | None:
    recommendation = attempt.source_recommendation
    if recommendation is None:
        recommendation = (
            RecommendationLog.objects.filter(
                user=attempt.user,
                task=attempt.task,
                recommended_at__gte=timezone.now() - timedelta(days=1),
            )
            .order_by("-recommended_at", "-created_at", "-id")
            .first()
        )
        if recommendation is None:
            return None
        Attempt.objects.filter(pk=attempt.pk).update(source_recommendation=recommendation)
        attempt.source_recommendation = recommendation

    recommendation.attempt = attempt
    if _attempt_successful(attempt):
        recommendation.status = RecommendationLog.Status.COMPLETED
        recommendation.completed = True
    else:
        recommendation.status = RecommendationLog.Status.ATTEMPTED
        recommendation.completed = False
    recommendation.save(update_fields=["attempt", "status", "completed", "updated_at"])
    return recommendation


def recommend_task_candidates(
    user,
    *,
    limit: int | None = None,
    log: bool = False,
    source_mode: str = RecommendationLog.SourceMode.UNKNOWN,
    exam_version=None,
    task_type_ids: list[int] | tuple[int, ...] | None = None,
    exclude_recent: bool = True,
    exclude_solved: bool = True,
) -> list[RecommendationCandidate]:
    now = timezone.now()
    tasks = list(
        _select_candidates(
            user,
            now,
            exam_version=exam_version,
            task_type_ids=task_type_ids,
            exclude_recent=exclude_recent,
            exclude_solved=exclude_solved,
        ).prefetch_related("tags", "skills")
    )
    candidates = [_mvp_candidate(user, task, now) for task in tasks]
    ranked = sorted(
        candidates,
        key=lambda candidate: (candidate.score, candidate.task.id),
        reverse=True,
    )
    if limit is not None:
        ranked = ranked[:limit]
    if log and ranked:
        _log_recommendations(user, ranked, source_mode=source_mode, now=now)
    return ranked


def recommend_tasks(
    user,
    *,
    limit: int | None = None,
    log: bool = False,
    source_mode: str = RecommendationLog.SourceMode.UNKNOWN,
    exam_version=None,
    task_type_ids: list[int] | tuple[int, ...] | None = None,
    exclude_recent: bool = True,
    exclude_solved: bool = True,
):
    """Return tasks sorted by descending recommendation priority."""
    return [
        candidate.task
        for candidate in recommend_task_candidates(
            user,
            limit=limit,
            log=log,
            source_mode=source_mode,
            exam_version=exam_version,
            task_type_ids=task_type_ids,
            exclude_recent=exclude_recent,
            exclude_solved=exclude_solved,
        )
    ]
