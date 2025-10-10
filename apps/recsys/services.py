from __future__ import annotations

from .models import Attempt, SkillMastery, TypeMastery

MASTERY_WEIGHT_MULTIPLIER = 0.2


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
        mastery.mastery += delta
        mastery.save(update_fields=["mastery", "updated_at"])

    type_mastery, _ = TypeMastery.objects.get_or_create(user=user, task_type=task.type)
    type_mastery.mastery += delta
    type_mastery.save(update_fields=["mastery", "updated_at"])
