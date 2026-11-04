"""Shared guards for training lifecycle and stale browser requests."""
import hashlib
import json

from django.contrib.auth import get_user_model
from rest_framework import exceptions

from apps.recsys.models import TrainingOperation, VariantAttempt


class TrainingConflict(exceptions.APIException):
    status_code = 409
    default_detail = "Состояние тренировки изменилось. Обновите данные и повторите действие."


def lock_user(user):
    # Every lifecycle transition takes this lock before locking attempts.
    get_user_model().objects.select_for_update(no_key=True).get(pk=user.pk)


def current_training(user, exam):
    return VariantAttempt.objects.filter(
        assignment__user=user, assignment__template__exam_version=exam,
        mode=VariantAttempt.Mode.TRAINING, archived_at__isnull=True, completed_at__isnull=True,
    ).order_by("-started_at", "-pk")


def ensure_writable(work, revision=None):
    if work.mode != VariantAttempt.Mode.TRAINING:
        return
    if work.archived_at or work.completed_at:
        raise TrainingConflict("Эта тренировка находится в архиве. Верните её к решению.")
    if revision is not None and revision != work.training_revision:
        raise TrainingConflict()


def operation_fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def replay(user, operation_id, fingerprint):
    if operation_id is None:
        return None
    previous = TrainingOperation.objects.filter(user=user, operation_id=operation_id).first()
    if previous:
        if previous.fingerprint != fingerprint:
            raise exceptions.ValidationError("Ключ операции уже использован для другого действия.")
        return previous.response
    return None


def receipt(user, operation_id, fingerprint, response):
    if operation_id is not None:
        TrainingOperation.objects.create(user=user, operation_id=operation_id, fingerprint=fingerprint, response=response)
    return response
