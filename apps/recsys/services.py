from __future__ import annotations

from .models import Attempt, SkillMastery, TypeMastery


def update_mastery(attempt: Attempt) -> None:
    """Update user mastery based on an attempt.

    This implementation increases mastery counters for related skills and task type
    when the attempt is marked as correct. Each additional attempt within the
    aggregation window contributes its ``attempts_count``.
    """
    user = attempt.user
    task = attempt.task
    count = attempt.attempts_count

    if not attempt.is_correct:
        # Do not modify mastery for incorrect attempts
        return

    for skill in task.skills.all():
        mastery, _ = SkillMastery.objects.get_or_create(user=user, skill=skill)
        mastery.mastery += count
        mastery.save(update_fields=["mastery", "updated_at"])

    type_mastery, _ = TypeMastery.objects.get_or_create(user=user, task_type=task.type)
    type_mastery.mastery += count
    type_mastery.save(update_fields=["mastery", "updated_at"])
