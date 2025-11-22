"""Business logic for working with exam variants.

The module contains helper functions that encapsulate the rules around variant
assignments and attempts.  Views use these helpers to keep the HTTP layer
simple while the behaviour is centralised and easy to unit test.  The
functions intentionally operate on model instances instead of raw dictionaries
so that serializers can decide how to present the data.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
import hashlib
from typing import Any, Iterable, List, Optional, Mapping

from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import exceptions

from apps.recsys.forms import compare_answers
from apps.recsys.models import (
    VariantAssignment,
    VariantAttempt,
    VariantTask,
    VariantTaskAttempt,
)
from . import task_generation


TASK_PREFETCH = Prefetch(
    "template__template_tasks",
    queryset=VariantTask.objects.select_related("task").order_by("order"),
)

TASK_ATTEMPTS_PREFETCH = Prefetch(
    "task_attempts",
    queryset=VariantTaskAttempt.objects.select_related("variant_task", "variant_task__task", "task").order_by(
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

    @transaction.atomic
    def _create_attempt_with_generation(assignment: VariantAssignment) -> VariantAttempt:
        assignment.mark_started()
        attempt = VariantAttempt.objects.create(
            assignment=assignment,
            attempt_number=next_number,
        )
        _materialize_tasks_for_attempt(attempt)
        return attempt

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

    return _create_attempt_with_generation(assignment)


def _materialize_tasks_for_attempt(attempt: VariantAttempt) -> None:
    template_tasks = list(
        attempt.assignment.template.template_tasks.select_related("task").all()
    )
    for variant_task in template_tasks:
        snapshot = _generate_task_snapshot(attempt, variant_task)
        if snapshot is None:
            continue
        VariantTaskAttempt.objects.create(
            variant_attempt=attempt,
            variant_task=variant_task,
            task=variant_task.task,
            attempt_number=0,
            is_correct=False,
            task_snapshot={"task": snapshot},
        )


def _generate_task_snapshot(
    attempt: VariantAttempt, variant_task: VariantTask
) -> Optional[dict]:
    task = variant_task.task
    if task is None:  # pragma: no cover - defensive
        return None

    image_url = task.image.url if task.image else None
    correct_answer = deepcopy(task.correct_answer or {})

    if task.is_dynamic:
        seed = _compute_task_seed(attempt, variant_task)

        if task.dynamic_mode == task.DynamicMode.PRE_GENERATED:
            dataset = task.pick_pregenerated_dataset(seed=seed)
            if dataset is None:
                raise exceptions.ValidationError(
                    "Для задачи не найдено предгенерированных наборов данных"
                )

            payload = deepcopy(dataset.parameter_values or {})
            rendered_statement = task.render_template_payload(payload)
            dataset_answer = deepcopy(dataset.correct_answer or {})

            snapshot: dict = {
                "type": "dynamic",
                "generation_mode": task.DynamicMode.PRE_GENERATED,
                "task_id": task.id,
                "dataset_id": dataset.id,
                "seed": seed,
                "rendering_strategy": task.rendering_strategy,
                "template": task.description,
                "payload": payload,
                "content": {
                    "title": task.title,
                    "statement": rendered_statement,
                },
                "image": image_url,
                "difficulty_level": task.difficulty_level,
            }

            if dataset_answer:
                snapshot["correct_answer"] = dataset_answer
                snapshot["answers"] = dataset_answer
            else:
                snapshot["correct_answer"] = correct_answer

            if dataset.meta:
                snapshot["meta"] = deepcopy(dataset.meta)

            return snapshot

        payload = deepcopy(task.default_payload or {})
        generation = task_generation.generate(
            task,
            payload,
            seed=seed,
            student=attempt.assignment.user,
        )

        used_payload = generation.payload or payload
        snapshot = {
            "type": "dynamic",
            "task_id": task.id,
            "generator_slug": task.generator_slug,
            "seed": seed,
            "rendering_strategy": task.rendering_strategy,
            "payload": dict(used_payload),
            "content": dict(generation.content),
            "image": image_url,
            "correct_answer": correct_answer,
            "difficulty_level": task.difficulty_level,
        }
        if generation.answers is not None:
            snapshot["answers"] = _normalise_answers(generation.answers)
        if generation.meta is not None:
            snapshot["meta"] = dict(generation.meta)
        return snapshot

    snapshot = {
        "type": "static",
        "task_id": task.id,
        "title": task.title,
        "description": task.description,
        "rendering_strategy": task.rendering_strategy,
        "image": image_url,
        "correct_answer": correct_answer,
        "difficulty_level": task.difficulty_level,
    }
    if task.default_payload:
        snapshot["payload"] = deepcopy(task.default_payload)
    return snapshot


def _compute_task_seed(attempt: VariantAttempt, variant_task: VariantTask) -> int:
    base = f"{attempt.assignment_id}:{attempt.id}:{variant_task.id}:{attempt.attempt_number}"
    digest = hashlib.sha256(base.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def _extract_generated_snapshot(
    attempts: list[VariantTaskAttempt],
) -> Optional[dict]:
    for attempt in attempts:
        if attempt.attempt_number == 0:
            task_snapshot = attempt.task_snapshot or {}
            snapshot = task_snapshot.get("task", task_snapshot)
            return deepcopy(snapshot)
    return None


def _get_generated_snapshot(
    attempt: VariantAttempt, variant_task: VariantTask
) -> Optional[dict]:
    generation_attempt = attempt.task_attempts.filter(
        variant_task=variant_task, attempt_number=0
    ).first()
    if not generation_attempt:
        return None
    snapshot = generation_attempt.task_snapshot or {}
    return deepcopy(snapshot.get("task", snapshot))


def _get_generation_attempt_for_update(
    attempt: VariantAttempt, variant_task: VariantTask
) -> Optional[VariantTaskAttempt]:
    return (
        VariantTaskAttempt.objects.select_for_update(of=("self",))
        .filter(
            variant_attempt=attempt,
            variant_task=variant_task,
            attempt_number=0,
        )
        .order_by("id")
        .first()
    )


def _normalise_answers(value):
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return value


@dataclass
class TaskSubmissionResult:
    attempt: VariantAttempt
    task_attempt: VariantTaskAttempt


@transaction.atomic
def save_task_response(
    user,
    attempt_id: int,
    variant_task_id: int,
    *,
    answer: Any,
) -> VariantTaskAttempt:
    """Persist (or overwrite) the draft response for a variant task."""

    try:
        attempt = (
            VariantAttempt.objects.select_for_update()
            .select_related("assignment__template")
            .prefetch_related(TASK_ATTEMPTS_PREFETCH)
            .get(pk=attempt_id, assignment__user=user)
        )
    except VariantAttempt.DoesNotExist as exc:
        raise exceptions.NotFound("Attempt does not exist or is unavailable.") from exc

    _ensure_active_attempt(attempt)
    _ensure_time_limit_allows_submission(attempt)

    assignment = attempt.assignment
    variant_task = _validate_variant_task(assignment, variant_task_id)

    generation_attempt = _get_generation_attempt_for_update(attempt, variant_task)
    if generation_attempt is None:
        _materialize_tasks_for_attempt(attempt)
        generation_attempt = _get_generation_attempt_for_update(attempt, variant_task)
        if generation_attempt is None:
            raise exceptions.ValidationError("Unable to prepare task snapshot for saving the answer.")

    snapshot = deepcopy(generation_attempt.task_snapshot or {})
    base_snapshot = snapshot.get("task")
    if base_snapshot is None:
        base_snapshot = _get_generated_snapshot(attempt, variant_task)
        if base_snapshot is not None:
            snapshot["task"] = base_snapshot

    snapshot["response"] = {
        "value": deepcopy(answer),
        "saved_at": timezone.now().isoformat(),
    }

    generation_attempt.task_snapshot = snapshot
    generation_attempt.save(update_fields=["task_snapshot", "updated_at"])
    return generation_attempt


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

    task_attempts_qs = attempt.task_attempts.filter(
        variant_task=variant_task, attempt_number__gt=0
    )
    next_number = task_attempts_qs.count() + 1
    task_limit = variant_task.max_attempts
    if task_limit is not None and next_number > task_limit:
        raise exceptions.ValidationError("Достигнут лимит попыток по заданию")

    base_snapshot = _get_generated_snapshot(attempt, variant_task)
    snapshot = {}
    if base_snapshot is not None:
        snapshot["task"] = base_snapshot
    if task_snapshot:
        snapshot["response"] = deepcopy(task_snapshot)
    if not snapshot:
        snapshot = {
            "task": {
                "type": "static",
                "task_id": variant_task.task_id,
                "title": variant_task.task.title,
                "description": variant_task.task.description,
                "rendering_strategy": variant_task.task.rendering_strategy,
                "image": variant_task.task.image.url
                if variant_task.task.image
                else None,
                "correct_answer": deepcopy(variant_task.task.correct_answer or {}),
                "difficulty_level": variant_task.task.difficulty_level,
            }
        }

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
    """Mark attempt as completed, evaluate answers, and persist time spent."""

    try:
        attempt = (
            VariantAttempt.objects.select_for_update()
            .select_related("assignment__template")
            .prefetch_related(TASK_ATTEMPTS_PREFETCH)
            .get(pk=attempt_id, assignment__user=user)
        )
    except VariantAttempt.DoesNotExist as exc:
        raise exceptions.NotFound("Attempt does not exist or is unavailable.") from exc

    _ensure_active_attempt(attempt)

    generation_attempts = [
        item
        for item in attempt.task_attempts.all()
        if item.attempt_number == 0
    ]
    for generation_attempt in generation_attempts:
        variant_task = generation_attempt.variant_task
        task = variant_task.task
        snapshot = deepcopy(generation_attempt.task_snapshot or {})
        task_snapshot = snapshot.get("task", snapshot)
        if not task_snapshot:
            base_snapshot = _get_generated_snapshot(attempt, variant_task)
            if base_snapshot is not None:
                task_snapshot = base_snapshot

        response_payload = snapshot.get("response")
        response_value = None
        if isinstance(response_payload, Mapping):
            if "value" in response_payload:
                response_value = response_payload.get("value")
            elif "answer" in response_payload:
                response_value = response_payload.get("answer")
            elif "text" in response_payload:
                response_value = response_payload.get("text")
        elif response_payload is not None:
            response_value = response_payload

        correct_answer = None
        if isinstance(task_snapshot, Mapping):
            correct_answer = deepcopy(task_snapshot.get("correct_answer"))
        if correct_answer is None and task is not None:
            correct_answer = deepcopy(task.correct_answer or {})

        computed_is_correct: bool | None = None
        if correct_answer is not None and response_value is not None:
            try:
                computed_is_correct = compare_answers(correct_answer, response_value)
            except Exception:  # pragma: no cover - defensive
                computed_is_correct = False

        actual_attempts_qs = attempt.task_attempts.filter(
            variant_task=variant_task,
            attempt_number__gt=0,
        ).order_by("attempt_number")
        next_number = actual_attempts_qs.count() + 1

        if actual_attempts_qs.exists():
            submission = actual_attempts_qs.last()
            updated_snapshot = deepcopy(submission.task_snapshot or {})
            if task_snapshot:
                updated_snapshot["task"] = deepcopy(task_snapshot)
            if response_payload is not None:
                updated_snapshot["response"] = deepcopy(response_payload)
            else:
                updated_snapshot.pop("response", None)
            final_is_correct = (
                submission.is_correct if computed_is_correct is None else bool(computed_is_correct)
            )
            submission.is_correct = final_is_correct
            submission.task_snapshot = updated_snapshot
            submission.save(update_fields=["is_correct", "task_snapshot", "updated_at"])
        else:
            record_snapshot = {}
            if task_snapshot:
                record_snapshot["task"] = deepcopy(task_snapshot)
            if response_payload is not None:
                record_snapshot["response"] = deepcopy(response_payload)
            VariantTaskAttempt.objects.create(
                variant_attempt=attempt,
                variant_task=variant_task,
                task=task,
                attempt_number=next_number,
                is_correct=bool(computed_is_correct),
                task_snapshot=record_snapshot,
            )

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
            if task_attempt.attempt_number == 0:
                continue
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
        generated_snapshot = None
        saved_response = None
        saved_response_updated_at = None
        for raw_attempt in task_attempts:
            if raw_attempt.attempt_number == 0:
                task_snapshot = raw_attempt.task_snapshot or {}
                snapshot_payload = task_snapshot.get("task", task_snapshot)
                if snapshot_payload and generated_snapshot is None:
                    generated_snapshot = deepcopy(snapshot_payload)
                response_payload = task_snapshot.get("response")
                if response_payload is not None:
                    if isinstance(response_payload, Mapping):
                        saved_response = deepcopy(response_payload.get("value", response_payload))
                    else:
                        saved_response = deepcopy(response_payload)
                    saved_response_updated_at = raw_attempt.updated_at
        actual_attempts = [
            attempt
            for attempt in task_attempts
            if attempt.attempt_number > 0
        ]
        progress.append(
            {
                "variant_task_id": variant_task.id,
                "task_id": variant_task.task_id,
                "order": variant_task.order,
                "max_attempts": variant_task.max_attempts,
                "attempts": actual_attempts,
                "attempts_used": len(actual_attempts),
                "is_completed": any(attempt.is_correct for attempt in actual_attempts),
                "task_snapshot": deepcopy(generated_snapshot) if generated_snapshot else None,
                "saved_response": deepcopy(saved_response) if saved_response is not None else None,
                "saved_response_updated_at": saved_response_updated_at,
            }
        )

    progress.sort(key=lambda item: item["order"])
    return progress

