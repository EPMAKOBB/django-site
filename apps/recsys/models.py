from __future__ import annotations

from copy import deepcopy

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from subjects.models import Subject


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Skill(TimeStampedModel):
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="skills"
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        unique_together = ("subject", "name")
        indexes = [models.Index(fields=["subject", "name"])]

    def __str__(self) -> str:
        return self.name


class TaskTag(TimeStampedModel):
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="task_tags"
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, blank=True)

    class Meta:
        ordering = ["name"]
        unique_together = ("subject", "name")
        indexes = [models.Index(fields=["subject", "name"])]

    def __str__(self) -> str:
        return self.name


class TaskType(TimeStampedModel):
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="task_types"
    )
    exam_version = models.ForeignKey(
        "ExamVersion",
        on_delete=models.CASCADE,
        related_name="task_types",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    required_tags = models.ManyToManyField(
        "TaskTag",
        blank=True,
        related_name="required_for_task_types",
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["subject", "exam_version", "name"],
                name="task_type_subject_exam_name_unique",
            )
        ]
        indexes = [
            models.Index(fields=["subject", "exam_version", "name"])
        ]

    def __str__(self) -> str:
        if self.exam_version:
            prefix = self.exam_version.name
            suffix = self.name
            return f"{prefix} · {suffix}"

        prefix = self.subject.name
        suffix = f"{self.name} (без версии экзамена)"
        return f"{prefix} · {suffix}"

    def clean(self):
        super().clean()

        if self.exam_version and self.exam_version.subject_id != self.subject_id:
            raise ValidationError(
                {"exam_version": "Версия экзамена должна соответствовать предмету"}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Task(TimeStampedModel):
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="tasks"
    )
    exam_version = models.ForeignKey(
        "ExamVersion",
        on_delete=models.CASCADE,
        related_name="tasks",
        null=True,
        blank=True,
    )
    type = models.ForeignKey(TaskType, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    skills = models.ManyToManyField("Skill", through="TaskSkill", related_name="tasks")
    tags = models.ManyToManyField(
        "TaskTag",
        blank=True,
        related_name="tasks",
    )
    is_dynamic = models.BooleanField(default=False)
    generator_slug = models.CharField(max_length=255, blank=True)
    default_payload = models.JSONField(default=dict, blank=True)
    image = models.ImageField(upload_to="tasks/screenshots/", blank=True)
    correct_answer = models.JSONField(blank=True, default=dict)
    difficulty_level = models.PositiveSmallIntegerField(default=0)
    first_attempt_total = models.PositiveIntegerField(default=0)
    first_attempt_failed = models.PositiveIntegerField(default=0)

    class RenderingStrategy(models.TextChoices):
        PLAIN = "plain", "Plain text"
        MARKDOWN = "markdown", "Markdown"
        HTML = "html", "HTML"

    rendering_strategy = models.CharField(
        max_length=32,
        choices=RenderingStrategy.choices,
        default=RenderingStrategy.MARKDOWN,
    )

    class Meta:
        unique_together = ("subject", "exam_version", "type", "title")
        indexes = [
            models.Index(fields=["subject", "exam_version", "type", "title"])
        ]

    def __str__(self) -> str:
        return self.title

    def clean(self):
        super().clean()

        payload = self.default_payload or {}
        if not isinstance(payload, dict):
            raise ValidationError(
                {"default_payload": "Payload должен быть объектом JSON"}
            )
        # Normalise JSON field to avoid shared mutable defaults
        self.default_payload = deepcopy(payload)

        answer = self.correct_answer or {}
        if not isinstance(answer, dict):
            raise ValidationError(
                {"correct_answer": "Правильный ответ должен быть объектом JSON"}
            )
        self.correct_answer = deepcopy(answer)

        if not 0 <= self.difficulty_level <= 100:
            raise ValidationError(
                {"difficulty_level": "Сложность должна быть в диапазоне 0–100"}
            )

        if self.is_dynamic:
            if not self.generator_slug:
                raise ValidationError(
                    {"generator_slug": "Для динамических задач требуется генератор"}
                )
            from apps.recsys.service_utils import task_generation

            if not task_generation.is_generator_registered(self.generator_slug):
                raise ValidationError(
                    {"generator_slug": "Указанный генератор не зарегистрирован"}
                )
        else:
            if self.generator_slug:
                raise ValidationError(
                    {"generator_slug": "Статические задачи не используют генератор"}
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class TaskSkill(TimeStampedModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE)
    weight = models.FloatField(default=1.0)

    def clean(self):
        if self.task.subject_id != self.skill.subject_id:
            raise ValidationError("Task and Skill must have the same subject")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    class Meta:
        unique_together = ("task", "skill")
        indexes = [
            models.Index(fields=["task"]),
            models.Index(fields=["skill"]),
        ]

    def __str__(self) -> str:
        return f"{self.task} - {self.skill}"


class ExamVersion(TimeStampedModel):
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="exam_versions"
    )
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["name"]
        unique_together = ("subject", "name")
        indexes = [models.Index(fields=["subject", "name"])]

    def __str__(self) -> str:
        return self.name


class SkillGroup(TimeStampedModel):
    exam_version = models.ForeignKey(
        ExamVersion, on_delete=models.CASCADE, related_name="skill_groups"
    )
    title = models.CharField(max_length=255)

    class Meta:
        unique_together = ("exam_version", "title")
        ordering = ["exam_version", "id"]

    def __str__(self) -> str:
        return self.title


class SkillGroupItem(TimeStampedModel):
    group = models.ForeignKey(
        SkillGroup, on_delete=models.CASCADE, related_name="items"
    )
    skill = models.ForeignKey(
        Skill, on_delete=models.CASCADE, related_name="group_items"
    )
    label = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("group", "skill")
        ordering = ["order"]
        indexes = [
            models.Index(fields=["group"]),
            models.Index(fields=["skill"]),
        ]

    def __str__(self) -> str:
        return f"{self.group} - {self.label}"


class Attempt(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attempts"
    )
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="attempts")
    is_correct = models.BooleanField(default=False)
    attempts_count = models.PositiveIntegerField(default=1)
    variant_task_attempt = models.ForeignKey(
        "VariantTaskAttempt",
        on_delete=models.CASCADE,
        related_name="attempts",
        null=True,
        blank=True,
    )
    weight = models.FloatField(default=1.0)

    class Meta:
        indexes = [models.Index(fields=["user", "task"])]

    def __str__(self) -> str:
        status = "correct" if self.is_correct else "incorrect"
        return f"{self.user} - {self.task} ({status})"


class SkillMastery(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="skill_masteries"
    )
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="masteries")
    mastery = models.FloatField(default=0.0)
    confidence = models.FloatField(default=0.0)

    class Meta:
        unique_together = ("user", "skill")
        indexes = [models.Index(fields=["user", "skill"])]

    def __str__(self) -> str:
        return f"{self.user} - {self.skill}: {self.mastery}"


class TypeMastery(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="type_masteries"
    )
    task_type = models.ForeignKey(
        TaskType, on_delete=models.CASCADE, related_name="masteries"
    )
    mastery = models.FloatField(default=0.0)
    confidence = models.FloatField(default=0.0)

    class Meta:
        unique_together = ("user", "task_type")
        indexes = [models.Index(fields=["user", "task_type"])]

    def __str__(self) -> str:
        return f"{self.user} - {self.task_type}: {self.mastery}"


class RecommendationLog(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recommendation_logs"
    )
    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name="recommendation_logs"
    )
    completed = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=["user", "task"])]

    def __str__(self) -> str:
        return f"{self.user} - {self.task}"


class VariantTemplate(TimeStampedModel):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    time_limit = models.DurationField(null=True, blank=True)
    max_attempts = models.PositiveIntegerField(null=True, blank=True)
    tasks = models.ManyToManyField(
        Task, through="VariantTask", related_name="variant_templates"
    )

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["name"])]

    def __str__(self) -> str:
        return self.name


class VariantTask(TimeStampedModel):
    template = models.ForeignKey(
        VariantTemplate, on_delete=models.CASCADE, related_name="template_tasks"
    )
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="variant_tasks")
    order = models.PositiveIntegerField()
    max_attempts = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["template", "order"]
        unique_together = (
            ("template", "order"),
            ("template", "task"),
        )
        indexes = [
            models.Index(fields=["template", "order"]),
            models.Index(fields=["template", "task"]),
        ]

    def __str__(self) -> str:
        return f"{self.template} -> {self.task}"


class VariantAssignment(TimeStampedModel):
    template = models.ForeignKey(
        VariantTemplate, on_delete=models.CASCADE, related_name="assignments"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="variant_assignments",
    )
    deadline = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["template"]),
            models.Index(fields=["user", "template"]),
        ]

    def mark_started(self) -> None:
        if self.started_at is None:
            self.started_at = timezone.now()
            self.save(update_fields=["started_at", "updated_at"])

    def __str__(self) -> str:
        return f"{self.user} - {self.template}"


class VariantAttempt(TimeStampedModel):
    assignment = models.ForeignKey(
        VariantAssignment, on_delete=models.CASCADE, related_name="attempts"
    )
    attempt_number = models.PositiveIntegerField(default=1)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    time_spent = models.DurationField(null=True, blank=True)

    class Meta:
        ordering = ["assignment", "attempt_number"]
        unique_together = ("assignment", "attempt_number")
        indexes = [
            models.Index(fields=["assignment", "attempt_number"]),
            models.Index(fields=["assignment"]),
        ]

    def mark_completed(self) -> None:
        if self.completed_at is None:
            self.completed_at = timezone.now()
            if self.time_spent is None:
                self.time_spent = self.completed_at - self.started_at
            self.save(update_fields=["completed_at", "time_spent", "updated_at"])

    def __str__(self) -> str:
        return f"Attempt {self.attempt_number} for {self.assignment}"


class VariantTaskAttempt(TimeStampedModel):
    variant_attempt = models.ForeignKey(
        VariantAttempt, on_delete=models.CASCADE, related_name="task_attempts"
    )
    variant_task = models.ForeignKey(
        VariantTask, on_delete=models.CASCADE, related_name="task_attempts"
    )
    task = models.ForeignKey(
        Task,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="variant_task_attempts",
    )
    attempt_number = models.PositiveIntegerField(default=1)
    is_correct = models.BooleanField(default=False)
    task_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["variant_attempt", "variant_task", "attempt_number"]
        unique_together = ("variant_attempt", "variant_task", "attempt_number")
        indexes = [
            models.Index(fields=["variant_attempt"]),
            models.Index(fields=["variant_task"]),
        ]

    def __str__(self) -> str:
        return (
            f"Task attempt {self.attempt_number} for {self.variant_task} "
            f"(variant attempt {self.variant_attempt.attempt_number})"
        )
