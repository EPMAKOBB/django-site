from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

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

    class Meta:
        ordering = ["name"]
        unique_together = ("subject", "exam_version", "name")
        indexes = [models.Index(fields=["subject", "exam_version", "name"])]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        if (
            self.exam_version_id is not None
            and self.exam_version.subject_id != self.subject_id
        ):
            raise ValidationError(
                "TaskType exam version must have the same subject as the task type"
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

    class Meta:
        unique_together = ("subject", "exam_version", "type", "title")
        indexes = [
            models.Index(fields=["subject", "exam_version", "type", "title"])
        ]

    def __str__(self) -> str:
        return self.title


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
