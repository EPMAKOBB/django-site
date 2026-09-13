"""Protect published annual configuration, including admin bulk deletion and M2M edits.

Data migrations and the lifecycle service deliberately use explicit SQL updates;
normal model/admin writes must create another revision for configuration changes.
"""
from django.core.exceptions import ValidationError
from django.db.models.signals import pre_save, pre_delete, m2m_changed
from django.dispatch import receiver

from .models import (
    AnswerSchema, ExamVersion, TaskType, ExamBlueprint, ExamBlueprintItem,
    ExamScoreScale, SkillGroup, SkillGroupItem, TaskTypeTransition,
)


FROZEN = {
    TaskType: "exam_version", ExamBlueprint: "exam_version",
    ExamBlueprintItem: "blueprint__exam_version", ExamScoreScale: "exam_version",
    SkillGroup: "exam_version", SkillGroupItem: "group__exam_version",
    TaskTypeTransition: "target_exam",
}
MESSAGE = "Опубликованная конфигурация защищена. Создайте новую редакцию экзамена."


def published_parent(instance, path):
    for part in path.split("__"):
        instance = getattr(instance, part, None)
        if instance is None:
            return False
    return ExamVersion.objects.filter(pk=instance.pk, published_at__isnull=False).exists()


@receiver(pre_save)
def protect_annual_write(sender, instance, raw=False, **kwargs):
    if raw or sender not in {*FROZEN, ExamVersion, AnswerSchema}:
        return
    old = sender.objects.filter(pk=instance.pk).first() if instance.pk else None
    fields = [f.attname for f in instance._meta.concrete_fields if f.name not in {"id", "created_at", "updated_at"}]
    changed = not old or any(getattr(old, key) != getattr(instance, key) for key in fields)
    if not changed:
        return
    if sender is TaskType and old and old.exam_version_id != instance.exam_version_id and old.recorded_attempts.exists():
        raise ValidationError("Тип с сохранёнными ответами нельзя переносить в другой экзамен.")
    if sender in FROZEN:
        path = FROZEN[sender]
        if published_parent(instance, path) or (old and published_parent(old, path)):
            raise ValidationError(MESSAGE)
    elif sender is ExamVersion:
        lifecycle = getattr(instance, "_annual_lifecycle", False)
        if old and old.published_at:
            allowed = {"status", "is_default"} if lifecycle else set()
            if any(getattr(old, key) != getattr(instance, key) for key in fields if key not in allowed):
                raise ValidationError(MESSAGE)
        if instance.copied_from_id and instance.status != ExamVersion.Status.DRAFT and not lifecycle:
            raise ValidationError("Публикуйте или архивируйте версию через проверку экзамена.")
    elif old and sender is AnswerSchema:
        if old.task_types.filter(exam_version__published_at__isnull=False).exists() or old.taskplacement_set.filter(task_type__exam_version__published_at__isnull=False).exists():
            raise ValidationError(MESSAGE)


@receiver(pre_delete)
def protect_annual_delete(sender, instance, **kwargs):
    if sender in FROZEN and published_parent(instance, FROZEN[sender]):
        raise ValidationError(MESSAGE)
    if sender is ExamVersion and instance.published_at:
        raise ValidationError(MESSAGE)


@receiver(m2m_changed, sender=TaskType.required_tags.through)
def protect_requirements(sender, instance, action, reverse, pk_set, **kwargs):
    if action not in {"pre_add", "pre_remove", "pre_clear"}:
        return
    if reverse:
        types = instance.required_for_task_types.all() if pk_set is None else TaskType.objects.filter(pk__in=pk_set)
        protected = types.filter(exam_version__published_at__isnull=False).exists()
    else:
        protected = bool(instance.exam_version_id and ExamVersion.objects.filter(pk=instance.exam_version_id, published_at__isnull=False).exists())
    if protected:
        raise ValidationError(MESSAGE)
