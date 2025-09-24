from django.db import models

from accounts.models import StudentProfile, TeacherProfile
from subjects.models import Subject


class Course(models.Model):
    class Level(models.TextChoices):
        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED = "advanced", "Advanced"

    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=255)
    subtitle = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    subject = models.ForeignKey(
        Subject, on_delete=models.PROTECT, related_name="courses", null=True, blank=True
    )
    level = models.CharField(
        max_length=20, choices=Level.choices, default=Level.BEGINNER
    )
    duration_weeks = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Approximate duration of the course in weeks",
    )
    owner = models.ForeignKey(
        TeacherProfile,
        on_delete=models.SET_NULL,
        related_name="courses",
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the course became visible to students",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["is_active", "published_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        return self.title


class CourseEnrollment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        CANCELED = "canceled", "Canceled"

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="enrollments"
    )
    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    progress = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Progress percentage from 0 to 100",
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ("course", "student")
        indexes = [
            models.Index(fields=["course", "student"]),
            models.Index(fields=["student", "status"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        return f"{self.student} -> {self.course}"
