
from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Attempt
from .services import update_mastery


@receiver(post_save, sender=Attempt)
def handle_attempt_post_save(sender, instance: Attempt, created: bool, **kwargs) -> None:
    """Aggregate quick repeated attempts and update mastery."""
    if not created:
        return

    five_minutes_ago = timezone.now() - timedelta(minutes=5)
    previous = (
        Attempt.objects.filter(
            user=instance.user,
            task=instance.task,
            created_at__gte=five_minutes_ago,
        )
        .exclude(pk=instance.pk)
        .order_by("-created_at")
        .first()
    )

    attempt_for_mastery = instance
    if previous:
        previous.attempts_count += instance.attempts_count
        previous.is_correct = instance.is_correct
        previous.save(update_fields=["attempts_count", "is_correct", "updated_at"])
        instance.delete()
        attempt_for_mastery = previous

    with transaction.atomic():
        update_mastery(attempt_for_mastery)

