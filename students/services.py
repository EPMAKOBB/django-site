import hashlib
import secrets
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import TeacherStudentLink

from .models import StudentAccountInvite, StudentRecord


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@transaction.atomic
def create_account_invite(*, student: StudentRecord, created_by, lifetime_days: int = 7):
    if student.user_id:
        raise ValidationError("К карточке уже привязан аккаунт.")
    StudentAccountInvite.objects.filter(
        student=student,
        used_at__isnull=True,
        revoked_at__isnull=True,
    ).update(revoked_at=timezone.now())
    raw_token = secrets.token_urlsafe(32)
    invite = StudentAccountInvite.objects.create(
        student=student,
        token_hash=_token_hash(raw_token),
        created_by=created_by,
        expires_at=timezone.now() + timedelta(days=lifetime_days),
    )
    return invite, raw_token


@transaction.atomic
def accept_account_invite(*, raw_token: str, user):
    try:
        invite = (
            StudentAccountInvite.objects.select_for_update()
            .select_related("student")
            .get(token_hash=_token_hash(raw_token))
        )
    except StudentAccountInvite.DoesNotExist as exc:
        raise ValidationError("Приглашение не найдено.") from exc
    if not invite.is_available:
        raise ValidationError("Приглашение уже использовано, отозвано или просрочено.")
    student = StudentRecord.objects.select_for_update().get(pk=invite.student_id)
    if student.user_id and student.user_id != user.id:
        raise ValidationError("К карточке уже привязан другой аккаунт.")
    if StudentRecord.objects.filter(user=user).exclude(pk=student.pk).exists():
        raise ValidationError("Этот аккаунт уже привязан к другой карточке ученика.")
    student.user = user
    student.save(update_fields=("user", "updated_at"))
    TeacherStudentLink.objects.filter(student_record=student).update(student=user)
    invite.used_at = timezone.now()
    invite.save(update_fields=("used_at",))
    return student
