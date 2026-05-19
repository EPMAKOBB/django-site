from __future__ import annotations

import math

from django.db.models import Max
from django.utils import timezone

from .models import Attempt, SkillMastery, TagMastery, Task, TypeMastery

MASTERY_WEIGHT_MULTIPLIER = 0.2
SUCCESS_THRESHOLD = 0.7
ALPHA_MASTERY = 0.15
BETA_COVERAGE = 0.08
GAMMA_PROGRESS = 0.1
K_CONFIDENCE = 5.0
DELTA_STABILITY = 0.08
LAMBDA_TIME = 0.5
LAMBDA_FORGET_BASE = 0.03
C_STABILITY = 2.0
K_DIFFICULTY = 30.0
MIN_ANALYTIC_TIME_SECONDS = 2.0
MAX_ANALYTIC_TIME_SECONDS = 4 * 60 * 60
MAX_EXPECTED_TIME_RATIO_FOR_ANALYTICS = 5.0

READINESS_BAND_FACTORS = {
    Task.LevelBand.INTRO: 0.10,
    Task.LevelBand.BASIC: 0.30,
    Task.LevelBand.EXAM: 1.00,
    Task.LevelBand.HARD: 1.30,
}

DIFFICULTY_PRIORS = {
    Task.LevelBand.INTRO: 0.20,
    Task.LevelBand.BASIC: 0.40,
    Task.LevelBand.EXAM: 0.55,
    Task.LevelBand.HARD: 0.75,
}


def _clamp_mastery(value: float | None) -> float:
    if value is None:
        return 0.0
    return max(0.0, min(1.0, float(value)))


def _normalised_score(attempt: Attempt) -> tuple[float, int]:
    max_score = int(attempt.max_score or attempt.task.get_max_score() or 1)
    if max_score <= 0:
        return 0.0, 0
    if attempt.score is None:
        raw_score = max_score if attempt.is_correct else 0.0
    else:
        raw_score = float(attempt.score)
    score_norm = max(0.0, min(1.0, raw_score / max_score))
    return score_norm, max_score


def _analytics_time_spent_seconds(attempt: Attempt) -> float | None:
    if attempt.time_spent is None:
        return None
    spent_seconds = attempt.time_spent.total_seconds()
    if spent_seconds < MIN_ANALYTIC_TIME_SECONDS:
        return None
    if spent_seconds > MAX_ANALYTIC_TIME_SECONDS:
        return None
    expected = int(attempt.task.expected_time_seconds or 0)
    if expected > 0 and spent_seconds > expected * MAX_EXPECTED_TIME_RATIO_FOR_ANALYTICS:
        return None
    return max(0.0, spent_seconds)


def _time_ratio(attempt: Attempt) -> float:
    expected = int(attempt.task.expected_time_seconds or 0)
    spent_seconds = _analytics_time_spent_seconds(attempt)
    if expected <= 0 or spent_seconds is None:
        return 1.0
    return spent_seconds / expected


def _quality_score(attempt: Attempt) -> tuple[float, float]:
    score_norm, _ = _normalised_score(attempt)
    time_ratio = _time_ratio(attempt)
    capped_ratio = max(0.0, min(time_ratio, 3.0))
    time_factor = math.exp(-LAMBDA_TIME * max(0.0, capped_ratio - 1.0))
    readiness_factor = READINESS_BAND_FACTORS.get(
        attempt.task.level_band,
        READINESS_BAND_FACTORS[Task.LevelBand.EXAM],
    )
    base_quality = score_norm * time_factor
    return base_quality * readiness_factor, score_norm


def _same_day(left, right) -> bool:
    if left is None or right is None:
        return False
    left_local = timezone.localtime(left) if timezone.is_aware(left) else left
    right_local = timezone.localtime(right) if timezone.is_aware(right) else right
    return left_local.date() == right_local.date()


def _normalised_task_difficulty_value(task: Task) -> float:
    raw = float(task.difficulty_level or 0.0)
    if raw > 1.0:
        raw = raw / 100.0
    return _clamp_mastery(raw)


def _difficulty_prior(task: Task) -> float:
    return DIFFICULTY_PRIORS.get(task.level_band, DIFFICULTY_PRIORS[Task.LevelBand.EXAM])


def _legacy_update_mastery(attempt: Attempt) -> None:
    """Keep the pre-MVP SkillMastery path alive during transition."""
    user = attempt.user
    task = attempt.task
    raw_delta = attempt.weight if attempt.is_correct else -attempt.weight
    delta = raw_delta * MASTERY_WEIGHT_MULTIPLIER

    if delta == 0:
        return

    for skill in task.skills.all():
        mastery, _ = SkillMastery.objects.get_or_create(user=user, skill=skill)
        mastery.mastery = _clamp_mastery(float(mastery.mastery or 0.0) + delta)
        mastery.save(update_fields=["mastery", "updated_at"])

    type_mastery, _ = TypeMastery.objects.get_or_create(user=user, task_type=task.type)
    type_mastery.mastery = _clamp_mastery(float(type_mastery.mastery or 0.0) + delta)
    type_mastery.save(update_fields=["mastery", "updated_at"])


def _update_task_aggregates(attempt: Attempt, score_norm: float, success_flag: int) -> None:
    task = attempt.task
    time_spent_seconds = _analytics_time_spent_seconds(attempt)
    task.attempts_total = int(task.attempts_total or 0) + 1
    task.score_norm_sum_total = float(task.score_norm_sum_total or 0.0) + score_norm
    task.difficulty_empirical = 1.0 - (task.score_norm_sum_total / task.attempts_total)
    if time_spent_seconds is not None:
        task.time_spent_sum_seconds = float(task.time_spent_sum_seconds or 0.0) + time_spent_seconds
        task.time_spent_count = int(task.time_spent_count or 0) + 1
        task.time_spent_avg_seconds = task.time_spent_sum_seconds / task.time_spent_count

    if attempt.attempt_number == 1:
        task.first_attempt_total = int(task.first_attempt_total or 0) + 1
        if not success_flag:
            task.first_attempt_failed = int(task.first_attempt_failed or 0) + 1

    task.save(
        update_fields=[
            "attempts_total",
            "score_norm_sum_total",
            "difficulty_empirical",
            "time_spent_sum_seconds",
            "time_spent_count",
            "time_spent_avg_seconds",
            "first_attempt_total",
            "first_attempt_failed",
            "updated_at",
        ]
    )


def _update_tag_masteries(attempt: Attempt, quality_score: float, score_norm: float) -> None:
    checked_at = attempt.checked_at or attempt.created_at
    success_flag = 1 if score_norm >= SUCCESS_THRESHOLD else 0

    for tag in attempt.task.tags.all():
        mastery_obj, _ = TagMastery.objects.get_or_create(user=attempt.user, task_tag=tag)
        old_mastery = float(mastery_obj.mastery or 0.0)
        old_coverage = float(mastery_obj.coverage or 0.0)
        old_progress = float(mastery_obj.progress or 0.0)
        old_stability = float(mastery_obj.stability or 0.0)

        mastery_obj.attempts_total = int(mastery_obj.attempts_total or 0) + 1
        mastery_obj.successes_total = int(mastery_obj.successes_total or 0) + success_flag
        mastery_obj.mastery = _clamp_mastery(
            (1.0 - ALPHA_MASTERY) * old_mastery + ALPHA_MASTERY * quality_score
        )
        mastery_obj.coverage = _clamp_mastery(
            min(1.0, old_coverage + (BETA_COVERAGE * quality_score))
        )
        progress_candidate = (1.0 - GAMMA_PROGRESS) * old_progress + GAMMA_PROGRESS * quality_score
        mastery_obj.progress = _clamp_mastery(max(old_progress, progress_candidate))
        mastery_obj.confidence = _clamp_mastery(
            1.0 - math.exp(-mastery_obj.attempts_total / K_CONFIDENCE)
        )
        if success_flag and not _same_day(mastery_obj.last_success_at, checked_at):
            mastery_obj.stability = _clamp_mastery(min(1.0, old_stability + DELTA_STABILITY))
        else:
            mastery_obj.stability = _clamp_mastery(old_stability)
        mastery_obj.last_seen_at = checked_at
        if success_flag:
            mastery_obj.last_success_at = checked_at
        mastery_obj.save()


def _update_type_mastery(attempt: Attempt) -> None:
    task_type = attempt.task.type
    type_mastery, _ = TypeMastery.objects.get_or_create(user=attempt.user, task_type=task_type)

    tag_masteries = TagMastery.objects.filter(
        user=attempt.user,
        task_tag__tasks__type=task_type,
    ).distinct()

    if tag_masteries.exists():
        mastery_values = list(tag_masteries.values_list("mastery", flat=True))
        coverage_values = list(tag_masteries.values_list("coverage", flat=True))
        progress_values = list(tag_masteries.values_list("progress", flat=True))
        confidence_values = list(tag_masteries.values_list("confidence", flat=True))
        stability_values = list(tag_masteries.values_list("stability", flat=True))
        count = len(mastery_values)
        type_mastery.mastery = _clamp_mastery(sum(mastery_values) / count)
        type_mastery.coverage = _clamp_mastery(sum(coverage_values) / count)
        type_mastery.progress = _clamp_mastery(sum(progress_values) / count)
        type_mastery.confidence = _clamp_mastery(sum(confidence_values) / count)
        type_mastery.stability = _clamp_mastery(sum(stability_values) / count)
        type_mastery.last_seen_at = tag_masteries.aggregate(value=Max("last_seen_at"))["value"]
        type_mastery.last_success_at = tag_masteries.aggregate(value=Max("last_success_at"))["value"]

    valid_attempts = Attempt.objects.filter(
        user=attempt.user,
        task__type=task_type,
        is_valid_attempt=True,
    )
    type_mastery.attempts_total = valid_attempts.count()
    successes_total = 0
    for valid_attempt in valid_attempts:
        score_norm, _ = _normalised_score(valid_attempt)
        if score_norm >= SUCCESS_THRESHOLD:
            successes_total += 1
    type_mastery.successes_total = successes_total
    if not tag_masteries.exists():
        # Transitional fallback for types that still have no tag data.
        raw_delta = attempt.weight if attempt.is_correct else -attempt.weight
        delta = raw_delta * MASTERY_WEIGHT_MULTIPLIER
        type_mastery.mastery = _clamp_mastery(float(type_mastery.mastery or 0.0) + delta)
    type_mastery.save()


def update_mastery(attempt: Attempt) -> None:
    """Update transition-era legacy mastery plus MVP tag/type/task analytics."""
    if not attempt.is_valid_attempt:
        return

    _legacy_update_mastery(attempt)
    quality_score, score_norm = _quality_score(attempt)
    success_flag = 1 if score_norm >= SUCCESS_THRESHOLD else 0
    _update_task_aggregates(attempt, score_norm, success_flag)
    _update_tag_masteries(attempt, quality_score, score_norm)
    _update_type_mastery(attempt)


def recompute_task_difficulty(task: Task) -> None:
    valid_attempts = list(
        Attempt.objects.filter(task=task, is_valid_attempt=True).select_related("task")
    )
    attempts_total = len(valid_attempts)
    score_norm_sum_total = 0.0
    time_spent_sum_seconds = 0.0
    time_spent_count = 0
    for attempt in valid_attempts:
        score_norm, _ = _normalised_score(attempt)
        score_norm_sum_total += score_norm
        time_spent_seconds = _analytics_time_spent_seconds(attempt)
        if time_spent_seconds is not None:
            time_spent_sum_seconds += time_spent_seconds
            time_spent_count += 1

    if attempts_total > 0:
        difficulty_empirical = 1.0 - (score_norm_sum_total / attempts_total)
    else:
        difficulty_empirical = _difficulty_prior(task)
    difficulty_empirical = _clamp_mastery(difficulty_empirical)
    weight = attempts_total / (attempts_total + K_DIFFICULTY)
    difficulty_level = (weight * difficulty_empirical) + ((1.0 - weight) * _difficulty_prior(task))

    task.attempts_total = attempts_total
    task.score_norm_sum_total = score_norm_sum_total
    task.time_spent_sum_seconds = time_spent_sum_seconds
    task.time_spent_count = time_spent_count
    task.time_spent_avg_seconds = (
        time_spent_sum_seconds / time_spent_count if time_spent_count else None
    )
    task.difficulty_empirical = difficulty_empirical
    task.difficulty_level = int(round(_clamp_mastery(difficulty_level) * 100))
    task.save(
        update_fields=[
            "attempts_total",
            "score_norm_sum_total",
            "time_spent_sum_seconds",
            "time_spent_count",
            "time_spent_avg_seconds",
            "difficulty_empirical",
            "difficulty_level",
            "updated_at",
        ]
    )


def recompute_task_difficulties(queryset=None) -> int:
    tasks = queryset if queryset is not None else Task.objects.all()
    count = 0
    for task in tasks.iterator():
        recompute_task_difficulty(task)
        count += 1
    return count


def apply_forgetting_to_tag_masteries(*, now=None, queryset=None) -> int:
    now = now or timezone.now()
    tag_masteries = queryset if queryset is not None else TagMastery.objects.all()
    updated = 0
    for mastery in tag_masteries.iterator():
        if mastery.last_success_at is None:
            continue
        delta_days = max(0.0, (now - mastery.last_success_at).total_seconds() / 86400.0)
        lambda_forget = LAMBDA_FORGET_BASE / (1.0 + C_STABILITY * float(mastery.stability or 0.0))
        mastery_decayed = _clamp_mastery(float(mastery.mastery or 0.0) * math.exp(-lambda_forget * delta_days))
        if abs(mastery_decayed - float(mastery.mastery or 0.0)) < 1e-9:
            continue
        mastery.mastery = mastery_decayed
        mastery.save(update_fields=["mastery", "updated_at"])
        updated += 1
    return updated


def recompute_type_masteries_from_tags(queryset=None) -> int:
    type_masteries = queryset if queryset is not None else TypeMastery.objects.all()
    updated = 0
    for type_mastery in type_masteries.iterator():
        tag_masteries = TagMastery.objects.filter(
            user=type_mastery.user,
            task_tag__tasks__type=type_mastery.task_type,
        ).distinct()
        if not tag_masteries.exists():
            continue

        mastery_values = list(tag_masteries.values_list("mastery", flat=True))
        coverage_values = list(tag_masteries.values_list("coverage", flat=True))
        progress_values = list(tag_masteries.values_list("progress", flat=True))
        confidence_values = list(tag_masteries.values_list("confidence", flat=True))
        stability_values = list(tag_masteries.values_list("stability", flat=True))
        count = len(mastery_values)

        type_mastery.mastery = _clamp_mastery(sum(mastery_values) / count)
        type_mastery.coverage = _clamp_mastery(sum(coverage_values) / count)
        type_mastery.progress = _clamp_mastery(sum(progress_values) / count)
        type_mastery.confidence = _clamp_mastery(sum(confidence_values) / count)
        type_mastery.stability = _clamp_mastery(sum(stability_values) / count)
        type_mastery.last_seen_at = tag_masteries.aggregate(value=Max("last_seen_at"))["value"]
        type_mastery.last_success_at = tag_masteries.aggregate(value=Max("last_success_at"))["value"]
        type_mastery.save(
            update_fields=[
                "mastery",
                "coverage",
                "progress",
                "confidence",
                "stability",
                "last_seen_at",
                "last_success_at",
                "updated_at",
            ]
        )
        updated += 1
    return updated


def refresh_student_recsys_state(user, *, now=None) -> dict[str, int]:
    now = now or timezone.now()
    forgetting_updates = apply_forgetting_to_tag_masteries(
        now=now,
        queryset=TagMastery.objects.filter(user=user),
    )
    type_updates = recompute_type_masteries_from_tags(
        queryset=TypeMastery.objects.filter(user=user),
    )
    return {
        "tag_forgetting": forgetting_updates,
        "type_masteries": type_updates,
    }
