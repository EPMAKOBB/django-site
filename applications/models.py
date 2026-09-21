from django.conf import settings
from django.db import models
from django.db.models import Q

from students.models import ContactPerson, StudentRecord
from subjects.models import Subject


class Application(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        CONTACTED = "contacted", "Contacted"
        QUALIFIED = "qualified", "Qualified"
        TRIAL_SCHEDULED = "trial_scheduled", "Trial scheduled"
        TRIAL_COMPLETED = "trial_completed", "Trial completed"
        CONVERTED = "converted", "Converted"
        LOST = "lost", "Lost"
        ARCHIVED = "archived", "Archived"
        PROCESSED = "processed", "Processed (legacy)"

    created_at = models.DateTimeField(auto_now_add=True)
    contact_name = models.CharField(max_length=255)
    student_name = models.CharField(max_length=255, null=True, blank=True)
    grade = models.PositiveSmallIntegerField(null=True, blank=True)
    subjects = models.ManyToManyField(Subject, related_name="applications", blank=True)
    contact_info = models.TextField()
    source_offer = models.CharField(max_length=255, null=True, blank=True)
    lesson_type = models.CharField(max_length=50, default="pass")
    status = models.CharField(
        max_length=20, choices=Status, default=Status.NEW
    )
    contact_person = models.ForeignKey(
        ContactPerson,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="applications",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_applications",
    )
    next_action_at = models.DateTimeField(null=True, blank=True)
    manager_notes = models.TextField(blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    lost_reason = models.TextField(blank=True)

    def __str__(self) -> str:  # type: ignore[override]
        return f"Application from {self.contact_name}"


class ApplicationStudent(models.Model):
    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name="student_links",
    )
    student = models.ForeignKey(
        StudentRecord,
        on_delete=models.PROTECT,
        related_name="application_links",
    )
    is_primary = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="application_student_links_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("application", "student"),
                name="application_student_unique",
            ),
            models.UniqueConstraint(
                fields=("application",),
                condition=Q(is_primary=True),
                name="application_one_primary_student",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.application} -> {self.student}"
