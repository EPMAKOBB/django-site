
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
    """Update attempt aggregates and mastery after creation."""
    if not created:
        return

    base_filter = {"user": instance.user, "task": instance.task}

    if instance.variant_task_attempt_id is not None:
        related_attempts = Attempt.objects.filter(
            variant_task_attempt=instance.variant_task_attempt,
            **base_filter,
        )
    else:
        five_minutes_ago = timezone.now() - timedelta(minutes=5)
        related_attempts = Attempt.objects.filter(
            created_at__gte=five_minutes_ago,
            variant_task_attempt__isnull=True,
            **base_filter,
        )

    total_attempts = related_attempts.count()
    weight = 1.0 / total_attempts if total_attempts else 1.0

    Attempt.objects.filter(pk=instance.pk).update(
        attempts_count=total_attempts or 1,
        weight=weight,
    )
    instance.refresh_from_db(fields=["attempts_count", "weight"])

    with transaction.atomic():
        update_mastery(instance)

