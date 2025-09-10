from django.db import models

from subjects.models import Subject


class Application(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        PROCESSED = "processed", "Processed"

    created_at = models.DateTimeField(auto_now_add=True)
    contact_name = models.CharField(max_length=255)
    student_name = models.CharField(max_length=255, null=True, blank=True)
    grade = models.PositiveSmallIntegerField(null=True, blank=True)
    subjects = models.ManyToManyField(Subject, related_name="applications", blank=True)
    contact_info = models.TextField()
    source_offer = models.CharField(max_length=255, null=True, blank=True)
    lesson_type = models.CharField(max_length=50, default="placeholder")
    status = models.CharField(
        max_length=10, choices=Status, default=Status.NEW
    )

    def __str__(self) -> str:  # type: ignore[override]
        return f"Application from {self.contact_name}"
