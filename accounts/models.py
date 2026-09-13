from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.crypto import get_random_string

from subjects.models import Subject
from apps.recsys.models import ExamVersion
from students.models import StudentRecord


DEFAULT_USER_TIMEZONE = "Europe/Moscow"


def validate_timezone_name(value: str) -> None:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValidationError("Укажите корректный часовой пояс IANA.") from exc


class UserPreferences(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    timezone = models.CharField(
        max_length=64,
        default=DEFAULT_USER_TIMEZONE,
        validators=[validate_timezone_name],
    )
    city = models.CharField(max_length=120, blank=True)
    timezone_confirmed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User preferences"
        verbose_name_plural = "User preferences"

    def __str__(self) -> str:
        return f"{self.user}: {self.timezone}"


class StudentProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)
    exam_versions = models.ManyToManyField(
        ExamVersion,
        blank=True,
        related_name="students_preparing",
        help_text="Выбранные версии экзаменов, к которым готовится студент",
    )

    def __str__(self):
        return f"{self.user.username} (student)"


class TeacherProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user.username} (teacher)"


class MethodistProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user.username} (methodist)"


class StudyClass(models.Model):
    """A study group/class that can include many students and teachers.

    Teachers are associated to a class per-subject using ClassTeacherSubject.
    Students join a class via a join code and are subject-agnostic members.
    """

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    join_code = models.CharField(max_length=16, unique=True, db_index=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="classes_created",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "name"]
        indexes = [models.Index(fields=["join_code"])]

    def __str__(self) -> str:  # pragma: no cover - representation only
        return self.name

    def save(self, *args, **kwargs):
        if not self.join_code:
            # Human-friendly short code, collision-resistant with uniqueness check
            self.join_code = get_random_string(10).lower()
        return super().save(*args, **kwargs)


class ClassStudentMembership(models.Model):
    class Meta:
        unique_together = ("study_class", "student")
        indexes = [
            models.Index(fields=["study_class", "student"]),
            models.Index(fields=["student"]),
        ]

    study_class = models.ForeignKey(
        StudyClass, on_delete=models.CASCADE, related_name="student_memberships"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="class_memberships"
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:  # pragma: no cover - representation only
        return f"{self.student} -> {self.study_class}"


class ClassTeacherSubject(models.Model):
    class Meta:
        unique_together = ("study_class", "teacher", "subject")
        indexes = [
            models.Index(fields=["study_class", "teacher", "subject"]),
            models.Index(fields=["teacher", "subject"]),
        ]

    study_class = models.ForeignKey(
        StudyClass, on_delete=models.CASCADE, related_name="teacher_subjects"
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="class_teachings"
    )
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="class_teachings")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:  # pragma: no cover - representation only
        return f"{self.study_class} · {self.subject} · {self.teacher}"


class TeacherStudentLink(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="student_links"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="teacher_links",
    )
    student_record = models.ForeignKey(
        StudentRecord,
        on_delete=models.PROTECT,
        related_name="teacher_links",
    )
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="teacher_student_links")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    default_duration_minutes = models.PositiveSmallIntegerField(
        default=60,
        validators=[MinValueValidator(1)],
    )
    default_price_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    currency = models.CharField(max_length=3, default="RUB")
    started_at = models.DateField(null=True, blank=True)
    ended_at = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    invite_code = models.CharField(max_length=20, unique=True, db_index=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("teacher", "student_record", "subject")
        indexes = [
            models.Index(
                fields=["teacher", "student_record", "subject"],
                name="accounts_tsr_subject_idx",
            ),
            models.Index(fields=["invite_code"], name="acct_tsl_invite_code_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - representation only
        return f"{self.teacher}⇄{self.student_display_name} @ {self.subject} ({self.status})"

    @property
    def student_user(self):
        return self.student_record.user or self.student

    @property
    def student_display_name(self) -> str:
        return self.student_record.full_name

    def save(self, *args, **kwargs):
        if not self.student_record_id:
            if not self.student_id:
                raise ValidationError("Укажите карточку ученика или его аккаунт.")
            user = self.student
            full_name = user.get_full_name() or user.username
            self.student_record, _ = StudentRecord.objects.get_or_create(
                user=user,
                defaults={
                    "full_name": full_name,
                    "status": StudentRecord.Status.ACTIVE,
                    "created_by": self.teacher,
                },
            )
        if not self.student_id and self.student_record.user_id:
            self.student_id = self.student_record.user_id
        if not self.invite_code:
            self.invite_code = get_random_string(12).lower()
        self.currency = (self.currency or "RUB").upper()
        return super().save(*args, **kwargs)


def teacher_has_subject_access(teacher, student, subject_id: int) -> bool:
    """Return True if the teacher is allowed to see student's data for subject.

    Allowed if there's an ACTIVE TeacherStudentLink for (teacher, student, subject)
    or they share a StudyClass where teacher teaches that subject.
    """

    if not teacher or not student or not subject_id:
        return False

    if TeacherStudentLink.objects.filter(
        teacher=teacher,
        student_record__user=student,
        subject_id=subject_id,
        status=TeacherStudentLink.Status.ACTIVE,
    ).exists():
        return True

    return ClassTeacherSubject.objects.filter(
        teacher=teacher,
        subject_id=subject_id,
        study_class__student_memberships__student=student,
    ).exists()


class TeacherSubjectInvite(models.Model):
    """An invite code for a student to connect with a teacher for a subject."""

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subject_invites"
    )
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="subject_invites")
    code = models.CharField(max_length=20, unique=True, db_index=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["teacher", "subject"])]

    def __str__(self) -> str:  # pragma: no cover - representation only
        return f"Invite {self.code} · {self.teacher} · {self.subject}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = get_random_string(12).lower()
        return super().save(*args, **kwargs)


class ClassInvite(models.Model):
    """Invite code for joining a class as a student."""

    study_class = models.ForeignKey(StudyClass, on_delete=models.CASCADE, related_name="invites")
    code = models.CharField(max_length=16, unique=True, db_index=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:  # pragma: no cover - representation only
        return f"ClassInvite {self.code} -> {self.study_class}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = get_random_string(10).lower()
        return super().save(*args, **kwargs)
