from __future__ import annotations

import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


DEFAULT_STUDENT_TIMEZONE = "Europe/Moscow"


def validate_timezone_name(value: str) -> None:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValidationError("Укажите корректный часовой пояс IANA.") from exc


class StudentRecord(models.Model):
    class Status(models.TextChoices):
        LEAD = "lead", "Потенциальный"
        CONTACTED = "contacted", "Связались"
        TRIAL = "trial", "Пробный период"
        ACTIVE = "active", "Занимается"
        PAUSED = "paused", "Пауза"
        FINISHED = "finished", "Закончил"
        LOST = "lost", "Отказался"
        ARCHIVED = "archived", "Архив"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    full_name = models.CharField(max_length=255)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.LEAD)
    grade = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(11)],
    )
    city = models.CharField(max_length=120, blank=True)
    timezone = models.CharField(
        max_length=64,
        default=DEFAULT_STUDENT_TIMEZONE,
        validators=[validate_timezone_name],
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="student_record",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="student_records_created",
    )
    notes = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("full_name", "id")
        indexes = [
            models.Index(fields=("status", "full_name"), name="students_status_name_idx"),
            models.Index(fields=("full_name",), name="students_full_name_idx"),
        ]

    def __str__(self) -> str:
        suffix = f" · {self.grade} класс" if self.grade else ""
        return f"{self.full_name}{suffix}"


class ContactPerson(models.Model):
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=32, blank=True, db_index=True)
    email = models.EmailField(blank=True, db_index=True)
    telegram_username = models.CharField(max_length=64, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="student_contact_persons",
    )
    timezone = models.CharField(
        max_length=64,
        blank=True,
        validators=[validate_timezone_name],
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("full_name", "id")

    def __str__(self) -> str:
        return self.full_name


class StudentContact(models.Model):
    class Relationship(models.TextChoices):
        SELF = "self", "Сам ученик"
        MOTHER = "mother", "Мать"
        FATHER = "father", "Отец"
        GUARDIAN = "guardian", "Опекун"
        RELATIVE = "relative", "Родственник"
        OTHER = "other", "Другое"

    student = models.ForeignKey(
        StudentRecord,
        on_delete=models.CASCADE,
        related_name="contact_links",
    )
    contact = models.ForeignKey(
        ContactPerson,
        on_delete=models.CASCADE,
        related_name="student_links",
    )
    relationship = models.CharField(max_length=16, choices=Relationship.choices)
    is_primary = models.BooleanField(default=False)
    is_payer = models.BooleanField(default=False)
    receives_schedule = models.BooleanField(default=True)
    receives_reschedules = models.BooleanField(default=True)
    receives_payment_notifications = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("student", "contact", "relationship"),
                name="student_contact_relationship_unique",
            ),
            models.UniqueConstraint(
                fields=("student",),
                condition=Q(is_primary=True, is_active=True),
                name="student_one_active_primary_contact",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.student} · {self.contact} ({self.get_relationship_display()})"


class StudentAccountInvite(models.Model):
    student = models.ForeignKey(
        StudentRecord,
        on_delete=models.CASCADE,
        related_name="account_invites",
    )
    token_hash = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="student_account_invites_created",
    )
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("student", "expires_at"),
                name="students_invite_expiry_idx",
            )
        ]

    @property
    def is_available(self) -> bool:
        from django.utils import timezone

        return self.used_at is None and self.revoked_at is None and self.expires_at > timezone.now()


class StudentStatusEvent(models.Model):
    student = models.ForeignKey(
        StudentRecord,
        on_delete=models.CASCADE,
        related_name="status_events",
    )
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(max_length=16, choices=StudentRecord.Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="student_status_changes",
    )
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
