
from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Attempt
from .recommendation import attach_attempt_to_recommendation
from .services import update_mastery
from . import annual_guards  # noqa: F401; register publication guards


def _invalidate_catalog(sender, using="default", raw=False, **kwargs):
    if not raw:
        from .service_utils.exam_catalog import invalidate_exam_catalog
        invalidate_exam_catalog(using=using)


def _invalidate_catalog_tags(sender, action, using="default", **kwargs):
    if action in {"post_add", "post_remove", "post_clear"}:
        _invalidate_catalog(sender, using=using)


from django.db.models.signals import post_delete, m2m_changed
from subjects.models import Subject
from .models import ExamVersion, TaskType, TaskTag, ExamBlueprint, ExamBlueprintItem, ExamScoreScale
from .models import SolutionPhoto


@receiver(post_delete, sender=SolutionPhoto)
def delete_solution_photo_file(sender, instance, **kwargs):
    if instance.image:
        storage, name = instance.image.storage, instance.image.name
        transaction.on_commit(lambda: storage.delete(name))

for _model in (Subject, ExamVersion, TaskType, TaskTag, ExamBlueprint, ExamBlueprintItem, ExamScoreScale):
    post_save.connect(_invalidate_catalog, sender=_model, dispatch_uid=f"catalog-save-{_model._meta.label}")
    post_delete.connect(_invalidate_catalog, sender=_model, dispatch_uid=f"catalog-delete-{_model._meta.label}")
m2m_changed.connect(_invalidate_catalog_tags, sender=TaskType.required_tags.through, dispatch_uid="catalog-tags")
m2m_changed.connect(_invalidate_catalog_tags, sender=TaskType.allowed_tags.through, dispatch_uid="catalog-allowed-tags")


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
        attempt_number=total_attempts or 1,
        mode=(
            Attempt.Mode.VARIANT if instance.variant_task_attempt_id is not None
            and instance.variant_task_attempt.variant_attempt.mode != "training" else Attempt.Mode.TRAINING
        ),
        checked_at=instance.checked_at or instance.created_at,
        weight=weight,
    )
    instance.refresh_from_db(fields=["attempts_count", "attempt_number", "mode", "checked_at", "weight"])

    with transaction.atomic():
        update_mastery(instance)
        attach_attempt_to_recommendation(instance)

