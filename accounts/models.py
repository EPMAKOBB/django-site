from django.conf import settings
from django.db import models
from django.utils.crypto import get_random_string

from subjects.models import Subject
from apps.recsys.models import ExamVersion


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
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="teacher_links"
    )
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="teacher_student_links")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    invite_code = models.CharField(max_length=20, unique=True, db_index=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("teacher", "student", "subject")
        indexes = [
            models.Index(fields=["teacher", "student", "subject"]),
            models.Index(fields=["invite_code"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - representation only
        return f"{self.teacher}⇄{self.student} @ {self.subject} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.invite_code:
            self.invite_code = get_random_string(12).lower()
        return super().save(*args, **kwargs)


def teacher_has_subject_access(teacher, student, subject_id: int) -> bool:
    """Return True if the teacher is allowed to see student's data for subject.

    Allowed if there's an ACTIVE TeacherStudentLink for (teacher, student, subject)
    or they share a StudyClass where teacher teaches that subject.
    """

    if not teacher or not student or not subject_id:
        return False

    if TeacherStudentLink.objects.filter(
        teacher=teacher, student=student, subject_id=subject_id, status=TeacherStudentLink.Status.ACTIVE
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
