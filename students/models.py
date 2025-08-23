"""Models for tracking courses, assignments and student submissions."""

from django.conf import settings
from django.db import models


class Course(models.Model):
    """A course containing multiple assignments."""

    title = models.CharField(max_length=255)

    def __str__(self) -> str:  # pragma: no cover - simple representation
        return self.title


class Assignment(models.Model):
    """An assignment that belongs to a course."""

    course = models.ForeignKey(
        Course, related_name="assignments", on_delete=models.CASCADE
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    def __str__(self) -> str:  # pragma: no cover - simple representation
        return self.title


class Submission(models.Model):
    """A student's submission for a particular assignment."""

    assignment = models.ForeignKey(
        Assignment, related_name="submissions", on_delete=models.CASCADE
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="submissions", on_delete=models.CASCADE
    )
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("assignment", "student")

    def __str__(self) -> str:  # pragma: no cover - simple representation
        return f"{self.student} - {self.assignment}"

