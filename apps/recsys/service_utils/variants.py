"""Business logic for working with exam variants.

The module contains helper functions that encapsulate the rules around variant
assignments and attempts.  Views use these helpers to keep the HTTP layer
simple while the behaviour is centralised and easy to unit test.  The
functions intentionally operate on model instances instead of raw dictionaries
so that serializers can decide how to present the data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable, List

from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import exceptions

from apps.recsys.models import (
    VariantAssignment,
    VariantAttempt,
    VariantTask,
    VariantTaskAttempt,
)


TASK_PREFETCH = Prefetch(
    "template__template_tasks",
    queryset=VariantTask.objects.select_related("task").order_by("order"),
)

TASK_ATTEMPTS_PREFETCH = Prefetch(
    "task_attempts",
    queryset=VariantTaskAttempt.objects.select_related("variant_task").order_by(
        "variant_task_id", "attempt_number", "id"
    ),
)

ATTEMPTS_PREFETCH = Prefetch(
    "attempts",
    queryset=VariantAttempt.objects.order_by("attempt_number").prefetch_related(
        TASK_ATTEMPTS_PREFETCH
    ),
)

ASSIGNMENT_TEMPLATE_PREFETCH = Prefetch(
    "assignment__template__template_tasks",
    queryset=VariantTask.objects.select_related("task").order_by("order"),
)


def _base_assignment_queryset():
    return (
        VariantAssignment.objects.select_related("template")
        .prefetch_related(TASK_PREFETCH, ATTEMPTS_PREFETCH)
        .order_by("-created_at")
    )


def get_assignments_for_user(user) -> List[VariantAssignment]:
    """Return all assignments for ``user`` with related data prefetched."""

    return list(_base_assignment_queryset().filter(user=user))


def _active_attempts(assignment: VariantAssignment) -> List[VariantAttempt]:
    return [attempt for attempt in assignment.attempts.all() if attempt.completed_at is None]


def _attempts_left(assignment: VariantAssignment) -> int | None:
    template_limit = assignment.template.max_attempts
    if template_limit is None:
        return None
    used = assignment.attempts.count()
    remaining = template_limit - used
    return max(0, remaining)


def _deadline_passed(assignment: VariantAssignment) -> bool:
    return bool(assignment.deadline and assignment.deadline < timezone.now())


def can_start_attempt(assignment: VariantAssignment) -> bool:
    """Return ``True`` if a new attempt can be started for ``assignment``."""

    if _deadline_passed(assignment):
        return False

    if _active_attempts(assignment):
        return False

    remaining = _attempts_left(assignment)
    if remaining is None:
        return True
    return remaining > 0


def split_assignments(assignments: Iterable[VariantAssignment]):
    """Split assignments into current and past buckets."""

    current: list[VariantAssignment] = []
    past: list[VariantAssignment] = []

    for assignment in assignments:
        if _active_attempts(assignment) or can_start_attempt(assignment):
            current.append(assignment)
        else:
            past.append(assignment)

    return current, past


def get_assignment_or_404(user, assignment_id: int) -> VariantAssignment:
    try:
        assignment = _base_assignment_queryset().get(user=user, pk=assignment_id)
    except VariantAssignment.DoesNotExist as exc:  # pragma: no cover - defensive
        raise exceptions.NotFound("Назначение варианта не найдено") from exc
    return assignment


def _ensure_active_attempt(attempt: VariantAttempt) -> None:
    if attempt.completed_at is not None:
        raise exceptions.ValidationError("Попытка уже завершена")


def _ensure_time_limit_allows_submission(attempt: VariantAttempt) -> None:
    time_limit = attempt.assignment.template.time_limit
    if not time_limit:
        return
    elapsed = timezone.now() - attempt.started_at
    if elapsed > time_limit:
        raise exceptions.ValidationError("Время на выполнение попытки истекло")


@transaction.atomic
def start_new_attempt(user, assignment_id: int) -> VariantAttempt:
    """Start a new attempt for ``assignment_id`` owned by ``user``."""

    try:
        assignment = (
            VariantAssignment.objects.select_for_update()
            .select_related("template")
            .get(user=user, pk=assignment_id)
        )
    except VariantAssignment.DoesNotExist as exc:
        raise exceptions.NotFound("Назначение варианта не найдено") from exc

    if assignment.deadline and assignment.deadline < timezone.now():
        raise exceptions.ValidationError("Дедлайн по варианту истёк")

    if assignment.attempts.filter(completed_at__isnull=True).exists():
        raise exceptions.ValidationError("У вас уже есть активная попытка")

    template_limit = assignment.template.max_attempts
    next_number = assignment.attempts.count() + 1
    if template_limit is not None and next_number > template_limit:
        raise exceptions.ValidationError("Достигнут лимит попыток для варианта")

    assignment.mark_started()
    attempt = VariantAttempt.objects.create(
        assignment=assignment,
        attempt_number=next_number,
    )

    return attempt


@dataclass
class TaskSubmissionResult:
    attempt: VariantAttempt
    task_attempt: VariantTaskAttempt


def _validate_variant_task(assignment: VariantAssignment, variant_task_id: int) -> VariantTask:
    try:
        variant_task = assignment.template.template_tasks.get(pk=variant_task_id)
    except VariantTask.DoesNotExist as exc:
        raise exceptions.ValidationError("Задание не относится к выбранному варианту") from exc
    return variant_task


@transaction.atomic
def submit_task_answer(
    user,
    attempt_id: int,
    variant_task_id: int,
    *,
    is_correct: bool,
    task_snapshot: dict | None = None,
) -> TaskSubmissionResult:
    """Persist an answer for a concrete task inside ``attempt``."""

    try:
        attempt = (
            VariantAttempt.objects.select_for_update()
            .select_related("assignment__template")
            .prefetch_related(TASK_ATTEMPTS_PREFETCH)
            .get(pk=attempt_id, assignment__user=user)
        )
    except VariantAttempt.DoesNotExist as exc:
        raise exceptions.NotFound("Попытка не найдена") from exc

    _ensure_active_attempt(attempt)
    _ensure_time_limit_allows_submission(attempt)

    assignment = attempt.assignment
    variant_task = _validate_variant_task(assignment, variant_task_id)

    task_attempts_qs = attempt.task_attempts.filter(variant_task=variant_task)
    next_number = task_attempts_qs.count() + 1
    task_limit = variant_task.max_attempts
    if task_limit is not None and next_number > task_limit:
        raise exceptions.ValidationError("Достигнут лимит попыток по заданию")

    snapshot = task_snapshot or {"task_id": variant_task.task_id, "title": variant_task.task.title}

    task_attempt = VariantTaskAttempt.objects.create(
        variant_attempt=attempt,
        variant_task=variant_task,
        task=variant_task.task,
        attempt_number=next_number,
        is_correct=is_correct,
        task_snapshot=snapshot,
    )

    return TaskSubmissionResult(attempt=attempt, task_attempt=task_attempt)


@transaction.atomic
def finalize_attempt(user, attempt_id: int) -> VariantAttempt:
    """Mark attempt as completed and persist time spent."""

    try:
        attempt = (
            VariantAttempt.objects.select_for_update()
            .select_related("assignment__template")
            .prefetch_related(TASK_ATTEMPTS_PREFETCH)
            .get(pk=attempt_id, assignment__user=user)
        )
    except VariantAttempt.DoesNotExist as exc:
        raise exceptions.NotFound("Попытка не найдена") from exc

    _ensure_active_attempt(attempt)

    now = timezone.now()
    time_limit = attempt.assignment.template.time_limit
    if time_limit and now - attempt.started_at > time_limit:
        attempt.time_spent = time_limit
    else:
        attempt.time_spent = now - attempt.started_at
    attempt.mark_completed()
    return attempt


def get_attempt_with_prefetch(user, attempt_id: int) -> VariantAttempt:
    try:
        return (
            VariantAttempt.objects.select_related("assignment__template")
            .prefetch_related(TASK_ATTEMPTS_PREFETCH, ASSIGNMENT_TEMPLATE_PREFETCH)
            .get(pk=attempt_id, assignment__user=user)
        )
    except VariantAttempt.DoesNotExist as exc:
        raise exceptions.NotFound("Попытка не найдена") from exc


def get_assignment_history(user, assignment_id: int) -> VariantAssignment:
    return get_assignment_or_404(user, assignment_id)


def get_attempts_left(assignment: VariantAssignment) -> int | None:
    return _attempts_left(assignment)


def get_time_left(attempt: VariantAttempt) -> timedelta | None:
    time_limit = attempt.assignment.template.time_limit
    if not time_limit:
        return None
    elapsed = timezone.now() - attempt.started_at
    remaining = time_limit - elapsed
    if remaining < timedelta(0):
        remaining = timedelta(0)
    return remaining


def calculate_assignment_progress(assignment: VariantAssignment) -> dict:
    template_tasks = list(assignment.template.template_tasks.all())
    solved_variant_task_ids = set()
    for attempt in assignment.attempts.all():
        for task_attempt in attempt.task_attempts.all():
            if task_attempt.is_correct:
                solved_variant_task_ids.add(task_attempt.variant_task_id)

    return {
        "total_tasks": len(template_tasks),
        "solved_tasks": len(solved_variant_task_ids),
        "remaining_tasks": max(0, len(template_tasks) - len(solved_variant_task_ids)),
    }


def build_tasks_progress(attempt: VariantAttempt) -> list[dict]:
    template_tasks = list(attempt.assignment.template.template_tasks.all())
    attempts_map: dict[int, list[VariantTaskAttempt]] = {}
    for task_attempt in attempt.task_attempts.all():
        attempts_map.setdefault(task_attempt.variant_task_id, []).append(task_attempt)

    progress = []
    for variant_task in template_tasks:
        task_attempts = attempts_map.get(variant_task.id, [])
        progress.append(
            {
                "variant_task_id": variant_task.id,
                "task_id": variant_task.task_id,
                "order": variant_task.order,
                "max_attempts": variant_task.max_attempts,
                "attempts": task_attempts,
                "attempts_used": len(task_attempts),
                "is_completed": any(attempt.is_correct for attempt in task_attempts),
            }
        )

    progress.sort(key=lambda item: item["order"])
    return progress

