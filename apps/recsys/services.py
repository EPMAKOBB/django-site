from __future__ import annotations

from .models import Attempt, SkillMastery, TypeMastery

MASTERY_WEIGHT_MULTIPLIER = 0.2


def _clamp_mastery(value: float | None) -> float:
    if value is None:
        return 0.0
    return max(0.0, min(1.0, float(value)))


def update_mastery(attempt: Attempt) -> None:
    """Update user mastery based on an attempt and its weight."""
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
