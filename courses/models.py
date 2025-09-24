from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


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
