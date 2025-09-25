from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class TimeStampedModel(models.Model):
    """Reusable timestamped base model for course entities."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Course(models.Model):
    class Level(models.TextChoices):
        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED = "advanced", "Advanced"

    class Language(models.TextChoices):
        RU = "ru", "Russian"
        EN = "en", "English"
        OTHER = "other", "Other"

    slug = models.SlugField(unique=True, db_index=True)
    title = models.CharField(max_length=255)
    subtitle = models.CharField(max_length=255, blank=True)
    short_description = models.TextField(blank=True)
    full_description = models.TextField(blank=True)
    cover_image = models.ImageField(upload_to="courses/covers/", blank=True)
    level = models.CharField(
        max_length=20,
        choices=Level.choices,
        default=Level.BEGINNER,
    )
    language = models.CharField(
        max_length=10,
        choices=Language.choices,
        default=Language.RU,
    )
    duration_weeks = models.PositiveSmallIntegerField(null=True, blank=True)
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Стоимость курса. Оставьте пустым для бесплатных курсов.",
    )
    is_active = models.BooleanField(default=True)
    enrollment_open = models.BooleanField(default=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    meta_title = models.CharField(max_length=255, blank=True)
    meta_description = models.TextField(blank=True)

    class Meta:
        ordering = ("title",)

    def __str__(self) -> str:
        return self.title


class CourseEnrollment(models.Model):
    class Status(models.TextChoices):
        APPLIED = "applied", "Applied"
        ENROLLED = "enrolled", "Enrolled"
        COMPLETED = "completed", "Completed"
        ARCHIVED = "archived", "Archived"

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="course_enrollments",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.APPLIED,
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    progress = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Прогресс обучения в процентах",
    )
    grade = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    certificate_code = models.CharField(max_length=64, blank=True)

    class Meta:
        unique_together = ("course", "student")
        verbose_name = "Course enrollment"
        verbose_name_plural = "Course enrollments"

    def __str__(self) -> str:
        return f"{self.student} → {self.course} ({self.status})"


class CourseModule(TimeStampedModel):
    class Kind(models.TextChoices):
        SELF_PACED = "self", "Самостоятельный"
        SKILL = "skill", "Прогресс по скилу"
        TASK_TYPE = "task_type", "Прогресс по типу заданий"

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="modules",
    )
    slug = models.SlugField(db_index=True)
    title = models.CharField(max_length=255)
    subtitle = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    skill = models.ForeignKey(
        "recsys.Skill",
        on_delete=models.PROTECT,
        related_name="course_modules",
        null=True,
        blank=True,
    )
    task_type = models.ForeignKey(
        "recsys.TaskType",
        on_delete=models.PROTECT,
        related_name="course_modules",
        null=True,
        blank=True,
    )
    rank = models.PositiveIntegerField(default=0)
    col = models.PositiveIntegerField(default=0)
    dx = models.IntegerField(default=0, help_text="Сдвиг вершины по оси X (px)")
    dy = models.IntegerField(default=0, help_text="Сдвиг вершины по оси Y (px)")
    is_locked = models.BooleanField(default=False)

    class Meta:
        ordering = ("course", "rank", "col", "slug")
        unique_together = ("course", "slug")
        indexes = [
            models.Index(fields=["course", "rank", "col"]),
        ]

    def clean(self):
        super().clean()

        if self.kind == self.Kind.SKILL:
            if not self.skill_id:
                raise ValidationError(
                    {"skill": "Для модуля скила требуется указать скил."}
                )
            if self.task_type_id:
                raise ValidationError(
                    {"task_type": "Модуль скила не должен ссылаться на тип заданий."}
                )
        elif self.kind == self.Kind.TASK_TYPE:
            if not self.task_type_id:
                raise ValidationError(
                    {"task_type": "Для модуля типа заданий требуется указать тип."}
                )
            if self.skill_id:
                raise ValidationError(
                    {"skill": "Модуль типа заданий не должен ссылаться на скил."}
                )
        else:
            if self.skill_id or self.task_type_id:
                raise ValidationError(
                    "Самостоятельный модуль не должен ссылаться на скил или тип заданий"
                )

    def __str__(self) -> str:
        return f"{self.course}: {self.title}"


class CourseTheoryCard(TimeStampedModel):
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="theory_cards",
    )
    slug = models.SlugField()
    title = models.CharField(max_length=255)
    subtitle = models.CharField(max_length=255, blank=True)
    content = models.TextField()

    class ContentFormat(models.TextChoices):
        MARKDOWN = "markdown", "Markdown"
        HTML = "html", "HTML"
        PLAIN = "plain", "Plain text"

    content_format = models.CharField(
        max_length=20,
        choices=ContentFormat.choices,
        default=ContentFormat.MARKDOWN,
    )
    estimated_duration_minutes = models.PositiveIntegerField(
        default=5, help_text="Оценка времени на изучение карточки"
    )
    difficulty_level = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Сложность карточки от 0 до 100",
    )

    class Meta:
        ordering = ("course", "slug")
        unique_together = ("course", "slug")

    def __str__(self) -> str:
        return f"{self.course}: {self.title}"


class CourseModuleItem(TimeStampedModel):
    class ItemKind(models.TextChoices):
        THEORY = "theory", "Карточка теории"
        TASK = "task", "Задание"

    module = models.ForeignKey(
        CourseModule,
        on_delete=models.CASCADE,
        related_name="items",
    )
    kind = models.CharField(max_length=20, choices=ItemKind.choices)
    theory_card = models.ForeignKey(
        CourseTheoryCard,
        on_delete=models.CASCADE,
        related_name="module_items",
        null=True,
        blank=True,
    )
    task = models.ForeignKey(
        "recsys.Task",
        on_delete=models.PROTECT,
        related_name="course_module_items",
        null=True,
        blank=True,
    )
    position = models.PositiveIntegerField(default=0)
    min_mastery_percent = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Минимальный прогресс по модулю, чтобы показывать элемент",
    )
    max_mastery_percent = models.PositiveSmallIntegerField(
        default=100,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Максимальный прогресс, при превышении которого элемент скрывается",
    )

    class Meta:
        ordering = ("module", "position", "id")
        unique_together = ("module", "position")
        indexes = [
            models.Index(fields=["module", "kind", "position"]),
        ]

    def clean(self):
        super().clean()

        if self.kind == self.ItemKind.THEORY and not self.theory_card_id:
            raise ValidationError(
                {"theory_card": "Для элемента теории необходимо выбрать карточку."}
            )
        if self.kind == self.ItemKind.TASK and not self.task_id:
            raise ValidationError({"task": "Для элемента задания необходимо выбрать задачу."})
        if self.kind == self.ItemKind.THEORY and self.task_id:
            raise ValidationError({"task": "Элемент теории не может ссылаться на задачу."})
        if self.kind == self.ItemKind.TASK and self.theory_card_id:
            raise ValidationError(
                {"theory_card": "Элемент задания не может ссылаться на карточку."}
            )
        if self.theory_card and self.theory_card.course_id != self.module.course_id:
            raise ValidationError(
                {"theory_card": "Карточка должна относиться к тому же курсу, что и модуль."}
            )
        if self.min_mastery_percent > self.max_mastery_percent:
            raise ValidationError(
                {"max_mastery_percent": "Максимальный порог должен быть ≥ минимального."}
            )

    def __str__(self) -> str:
        target = self.theory_card or self.task
        return f"{self.module} → {target}"

    @property
    def difficulty_level(self) -> int:
        if self.kind == self.ItemKind.THEORY and self.theory_card:
            return self.theory_card.difficulty_level
        if self.kind == self.ItemKind.TASK and self.task:
            return getattr(self.task, "difficulty_level", 0)
        return 0
