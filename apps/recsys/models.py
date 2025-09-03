from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Subject(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["name"])]

    def __str__(self) -> str:
        return self.name


class ExamVersion(TimeStampedModel):
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="exam_versions"
    )
    exam_type = models.CharField(max_length=100)
    year = models.PositiveIntegerField()
    label = models.CharField(max_length=255)

    class Meta:
        unique_together = ("subject", "exam_type", "year")
        indexes = [
            models.Index(fields=["subject", "exam_type", "year"]),
        ]

    def __str__(self) -> str:
        return self.label


class Skill(TimeStampedModel):
    exam_version = models.ForeignKey(
        ExamVersion,
        on_delete=models.CASCADE,
        related_name="skills",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["name"])]

    def __str__(self) -> str:
        return self.name


class TaskType(TimeStampedModel):
    exam_version = models.ForeignKey(
        ExamVersion,
        on_delete=models.CASCADE,
        related_name="task_types",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["name"])]

    def __str__(self) -> str:
        return self.name


class Task(TimeStampedModel):
    type = models.ForeignKey(TaskType, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    skills = models.ManyToManyField("Skill", through="TaskSkill", related_name="tasks")

    class Meta:
        unique_together = ("type", "title")
        indexes = [models.Index(fields=["type", "title"])]

    def __str__(self) -> str:
        return self.title


class TaskSkill(TimeStampedModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE)
    weight = models.FloatField(default=1.0)

    class Meta:
        unique_together = ("task", "skill")
        indexes = [
            models.Index(fields=["task"]),
            models.Index(fields=["skill"]),
        ]

    def __str__(self) -> str:
        return f"{self.task} - {self.skill}"


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
