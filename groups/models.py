"""Models for managing student groups and invitation codes."""

import uuid

from django.conf import settings
from django.db import models


def generate_code() -> str:
    """Generate a short unique invitation code."""
    return uuid.uuid4().hex[:8].upper()


class Group(models.Model):
    """A group of students managed by a teacher."""

    name = models.CharField(max_length=255)
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="teaching_groups",
    )
    students = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="student_groups",
        blank=True,
    )

    def __str__(self) -> str:  # pragma: no cover - simple representation
        return self.name


class InvitationCode(models.Model):
    """Invitation codes used by students to join a group."""

    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, related_name="codes"
    )
    code = models.CharField(
        max_length=12, unique=True, default=generate_code
    )
    created_at = models.DateTimeField(auto_now_add=True)
    used_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="used_codes",
    )

    def __str__(self) -> str:  # pragma: no cover - simple representation
        return f"{self.code} for {self.group}"
