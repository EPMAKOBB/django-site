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
from pathlib import Path
from typing import Any, Iterable, List, Optional, Mapping

from django.db import transaction
from django.db.models import Prefetch, Sum
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import exceptions

from apps.recsys.forms import compare_answers
from apps.recsys.utils.rendering import render_task_body
from apps.recsys.models import (
    ExamBlueprint,
    ExamScoreScale,
    Task,
    TaskAttachment,
    TaskType,
    VariantAssignment,
    VariantAttempt,
    VariantPage,
    VariantTemplate,
    VariantTask,
    VariantTaskAttempt,
    VariantTaskTimeLog,
)
from apps.recsys.recommendation import recommend_tasks
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

def _render_task_body(description: str, rendering_strategy: str | None) -> str:
    return render_task_body(description, rendering_strategy)


def _build_task_attachments_payload(task: Task) -> list[dict]:
    attachments_payload: list[dict] = []
    for attachment in task.attachments.all():
        if attachment.kind != TaskAttachment.Kind.FILE:
            continue
        try:
            url = attachment.file.url
        except Exception:
            continue
        name = attachment.download_name_override or Path(attachment.file.name).name
        attachments_payload.append(
            {
                "id": attachment.id,
                "name": name or "download",
                "label": attachment.label or "",
                "url": url,
            }
        )
    return attachments_payload

ATTEMPTS_PREFETCH = Prefetch(
    "attempts",
    queryset=VariantAttempt.objects.order_by("attempt_number").prefetch_related(
        TASK_ATTEMPTS_PREFETCH
    ),
)


def ensure_variant_page(template: VariantTemplate, *, is_public: bool | None = None) -> VariantPage:
    """Return existing VariantPage for template or create one with a unique slug."""

    desired_public = template.is_public if is_public is None else is_public
    base_slug = template.slug or slugify(template.name or "") or f"variant-{template.id}"
    if not base_slug:
        base_slug = f"variant-{template.id}"
    slug_candidate = base_slug
    suffix = 2
    while VariantPage.objects.filter(slug=slug_candidate).exclude(template=template).exists():
        slug_candidate = f"{base_slug}-{suffix}"
        suffix += 1

    defaults = {
        "slug": slug_candidate,
        "title": template.name or "",
        "description": template.description or "",
        "is_public": desired_public,
    }
    page, created = VariantPage.objects.get_or_create(template=template, defaults=defaults)
    updates: dict[str, object] = {}
    if not created:
        if desired_public is not None and page.is_public != desired_public:
            updates["is_public"] = desired_public
        if not page.title and defaults["title"]:
            updates["title"] = defaults["title"]
        if not page.description and defaults["description"]:
            updates["description"] = defaults["description"]
    if updates:
        for field, value in updates.items():
            setattr(page, field, value)
        page.save(update_fields=list(updates.keys()) + ["updated_at"])
    return page

ASSIGNMENT_TEMPLATE_PREFETCH = Prefetch(
    "assignment__template__template_tasks",
    queryset=VariantTask.objects.select_related("task").order_by("order"),
)
 
def _get_active_blueprint(exam_version):
    return (
        ExamBlueprint.objects.filter(exam_version=exam_version, is_active=True)
        .select_related("exam_version", "subject")
        .prefetch_related("items__task_type")
        .order_by("-updated_at", "-id")
        .first()
    )


def _count_task_types(template_tasks: Iterable[VariantTask]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for variant_task in template_tasks:
        task = variant_task.task
        if not task or not task.type_id:
            continue
        counts[int(task.type_id)] = counts.get(int(task.type_id), 0) + 1
    return counts


def template_matches_blueprint(template: VariantTemplate) -> tuple[bool, ExamBlueprint | None]:
    exam_version = template.exam_version
    if not exam_version:
        return False, None
    blueprint = _get_active_blueprint(exam_version)
    if blueprint is None:
        return False, None

    template_tasks = list(
        template.template_tasks.select_related("task__type").all()
    )
    for variant_task in template_tasks:
        task = variant_task.task
        if not task or task.exam_version_id != exam_version.id:
            return False, blueprint

    blueprint_counts = {
        int(item.task_type_id): int(item.count or 0)
        for item in blueprint.items.all()
    }
    template_counts = _count_task_types(template_tasks)
    return template_counts == blueprint_counts, blueprint


def get_active_score_scale(exam_version) -> ExamScoreScale | None:
    if not exam_version:
        return None
    return (
        ExamScoreScale.objects.filter(exam_version=exam_version, is_active=True)
        .order_by("-updated_at", "-id")
        .first()
    )


def calculate_attempt_primary_summary(attempt: VariantAttempt) -> dict:
    template_tasks = list(
        attempt.assignment.template.template_tasks.select_related("task").all()
    )
    primary_max_total = 0
    for variant_task in template_tasks:
        task = variant_task.task
        if task:
            primary_max_total += task.get_max_score()

    latest_attempts: dict[int, VariantTaskAttempt] = {}
    for task_attempt in attempt.task_attempts.all():
        if task_attempt.attempt_number <= 0:
            continue
        prev = latest_attempts.get(task_attempt.variant_task_id)
        if prev is None or task_attempt.attempt_number > prev.attempt_number:
            latest_attempts[task_attempt.variant_task_id] = task_attempt

    primary_total = 0
    for attempt_entry in latest_attempts.values():
        if attempt_entry.score is None:
            continue
        try:
            primary_total += int(attempt_entry.score)
        except (TypeError, ValueError):
            continue

    success_percent = (
        round((primary_total / primary_max_total) * 100, 1)
        if primary_max_total
        else 0.0
    )

    return {
        "primary_total": primary_total,
        "primary_max_total": primary_max_total,
        "success_percent": success_percent,
    }

def build_personal_assignment_from_blueprint(*, user, exam_version):
    """Create a personal assignment based on the active exam blueprint."""

    blueprint = _get_active_blueprint(exam_version)
    if blueprint is None:
        raise exceptions.ValidationError("Нет активного чертежа экзамена.")

    items = list(blueprint.items.select_related("task_type").order_by("order", "id"))
    if not items:
        raise exceptions.ValidationError("Чертёж не содержит типов заданий.")

    recommended = recommend_tasks(user)
    recommended_by_type: dict[int, list[int]] = {}
    for task in recommended:
        if task.exam_version_id != exam_version.id or task.type_id is None:
            continue
        recommended_by_type.setdefault(int(task.type_id), []).append(int(task.id))

    selected_tasks: list[Task] = []
    used_task_ids: set[int] = set()
    for item in items:
        needed = max(1, int(item.count or 0))
        selected_ids: list[int] = []

        for tid in recommended_by_type.get(int(item.task_type_id), []):
            if tid in used_task_ids:
                continue
            selected_ids.append(tid)
            used_task_ids.add(tid)
            if len(selected_ids) >= needed:
                break

        if len(selected_ids) < needed:
            fallback_qs = (
                Task.objects.filter(type=item.task_type, exam_version=exam_version)
                .exclude(id__in=used_task_ids)
                .order_by("-difficulty_level", "id")
            )
            for tid in fallback_qs.values_list("id", flat=True)[: needed - len(selected_ids)]:
                selected_ids.append(int(tid))
                used_task_ids.add(int(tid))

        task_map = {t.id: t for t in Task.objects.filter(id__in=selected_ids)}
        for tid in selected_ids:
            task = task_map.get(tid)
            if task:
                selected_tasks.append(task)

    if not selected_tasks:
        raise exceptions.ValidationError("Не удалось подобрать задания для варианта.")

    now = timezone.now()
    existing_assignments = (
        VariantAssignment.objects.filter(
            user=user,
            template__exam_version=exam_version,
            template__kind=VariantTemplate.Kind.PERSONAL,
        )
        .select_related("template")
        .prefetch_related(ATTEMPTS_PREFETCH)
        .order_by("-created_at")
    )
    for assignment in existing_assignments:
        if assignment.deadline and assignment.deadline < now:
            continue
        if _active_attempts(assignment):
            ensure_variant_page(assignment.template, is_public=False)
            return assignment
        attempts_left = _attempts_left(assignment)
        if attempts_left is None or attempts_left > 0:
            ensure_variant_page(assignment.template, is_public=False)
            return assignment

    timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
    variant_name = f"Персональный вариант {exam_version.name} {user.id}-{timestamp}"
    with transaction.atomic():
        template = VariantTemplate.objects.create(
            name=variant_name,
            description=f"Сформирован из чертежа {blueprint.title or blueprint.pk}",
            exam_version=exam_version,
            time_limit=blueprint.time_limit,
            max_attempts=blueprint.max_attempts,
            kind=VariantTemplate.Kind.PERSONAL,
            is_public=False,
            display_order=0,
        )
        for order, task in enumerate(selected_tasks, start=1):
            VariantTask.objects.create(
                template=template,
                task=task,
                order=order,
                max_attempts=None,
            )
        assignment = VariantAssignment.objects.create(
            template=template,
            user=user,
        )
        ensure_variant_page(template, is_public=False)
    return assignment


def _as_list(value):
    if isinstance(value, Mapping):
        return list(value.values())
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _as_rows(value):
    raw_rows: list[Any] = []
    if isinstance(value, Mapping):
        raw_rows = list(value.values())
    elif isinstance(value, (list, tuple)):
        raw_rows = list(value)
    rows: list[list[Any]] = []
    for row in raw_rows:
        if isinstance(row, Mapping):
            base_row = list(row.values())
        elif isinstance(row, (list, tuple)):
            base_row = list(row)
        else:
            base_row = [row]
        rows.append(base_row)
    return rows


def _resolve_scoring(task: Task | None, snapshot: Mapping | None) -> tuple[str, int]:
    scheme = None
    max_score = None
    if snapshot:
        scheme = snapshot.get("scoring_scheme")
        max_score = snapshot.get("max_score")
    if task is not None:
        scheme = scheme or task.get_scoring_scheme()
        max_score = max_score or task.get_max_score()
    if not scheme:
        scheme = TaskType.ScoringScheme.BINARY
    try:
        max_score_int = int(max_score) if max_score is not None else 1
    except Exception:
        max_score_int = 1
    return scheme, max_score_int


def _grade_answer(
    scoring_scheme: str,
    correct_answer: Any,
    response_value: Any,
    *,
    max_score: int,
) -> tuple[Optional[int], Optional[bool]]:
    if scoring_scheme == TaskType.ScoringScheme.MANUAL_SCALED:
        return None, None

    if scoring_scheme == TaskType.ScoringScheme.PARTIAL_PAIRS:
        expected = _as_list(correct_answer)[:2]
        actual = _as_list(response_value)[:2]
        score = 0
        for idx in range(min(len(expected), len(actual))):
            try:
                if compare_answers(expected[idx], actual[idx]):
                    score += 1
            except Exception:
                continue
        score = min(score, max_score)
        return score, score == max_score

    if scoring_scheme == TaskType.ScoringScheme.PARTIAL_ROWS:
        expected_rows = _as_rows(correct_answer)[:2]
        actual_rows = _as_rows(response_value)[:2]
        score = 0
        for idx in range(min(len(expected_rows), len(actual_rows))):
            exp_row = expected_rows[idx][:2]
            act_row = actual_rows[idx][:2]
            if len(act_row) < len(exp_row):
                continue
            row_ok = True
            for value_idx in range(len(exp_row)):
                try:
                    if not compare_answers(exp_row[value_idx], act_row[value_idx]):
                        row_ok = False
                        break
                except Exception:
                    row_ok = False
                    break
            if row_ok:
                score += 1
        score = min(score, max_score)
        return score, score == max_score

    # Default/binary scoring
    try:
        is_correct = compare_answers(correct_answer, response_value)
    except Exception:
        is_correct = False
    return (max_score if is_correct else 0), bool(is_correct)


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
    now = timezone.now()
    elapsed = now - attempt.started_at
    if elapsed > time_limit:
        _apply_attempt_timeout(attempt, now=now)
        raise exceptions.ValidationError("Attempt time limit exceeded.")


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


@transaction.atomic
def set_active_task(user, attempt_id: int, variant_task_id: int) -> VariantAttempt:
    """Mark which task is currently opened by the student to manage per-task timers."""

    try:
        attempt = (
            VariantAttempt.objects.select_for_update()
            .select_related("assignment__template")
            .get(pk=attempt_id, assignment__user=user)
        )
    except VariantAttempt.DoesNotExist as exc:
        raise exceptions.NotFound("Attempt does not exist or is unavailable.") from exc

    now = timezone.now()
    if _apply_attempt_timeout(attempt, now=now):
        return attempt
    _ensure_active_attempt(attempt)
    _ensure_time_limit_allows_submission(attempt)
    if not _should_track_time(attempt):
        return attempt

    assignment = attempt.assignment
    variant_task = _validate_variant_task(assignment, variant_task_id)

    # If the same task is already active but timer is missing, restart it.
    if attempt.active_variant_task_id == variant_task.id:
        if attempt.active_started_at is None:
            _start_task_timer(attempt, variant_task, now=now)
        return attempt

    _stop_active_task_timer(
        attempt,
        reason=VariantTaskTimeLog.StopReason.SWITCH,
        now=now,
    )
    _start_task_timer(attempt, variant_task, now=now)
    return attempt


def _materialize_tasks_for_attempt(attempt: VariantAttempt) -> None:
    template_tasks = list(
        attempt.assignment.template.template_tasks.select_related("task").prefetch_related(
            "task__attachments"
        ).all()
    )
    for variant_task in template_tasks:
        snapshot = _generate_task_snapshot(attempt, variant_task)
        if snapshot is None:
            continue
        max_score = snapshot.get("max_score", 1)
        VariantTaskAttempt.objects.create(
            variant_attempt=attempt,
            variant_task=variant_task,
            task=variant_task.task,
            attempt_number=0,
            is_correct=False,
            max_score=max_score,
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
    scoring_scheme = task.get_scoring_scheme()
    max_score = task.get_max_score()
    attachments = _build_task_attachments_payload(task)

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
                "scoring_scheme": scoring_scheme,
                "max_score": max_score,
            }

            if dataset_answer:
                snapshot["correct_answer"] = dataset_answer
                snapshot["answers"] = dataset_answer
            else:
                snapshot["correct_answer"] = correct_answer

            if dataset.meta:
                snapshot["meta"] = deepcopy(dataset.meta)
            if attachments:
                snapshot["attachments"] = attachments

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
            "scoring_scheme": scoring_scheme,
            "max_score": max_score,
        }
        if generation.answers is not None:
            snapshot["answers"] = _normalise_answers(generation.answers)
        if generation.meta is not None:
            snapshot["meta"] = dict(generation.meta)
        if attachments:
            snapshot["attachments"] = attachments
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
        "scoring_scheme": scoring_scheme,
        "max_score": max_score,
    }
    if task.default_payload:
        snapshot["payload"] = deepcopy(task.default_payload)
    if attachments:
        snapshot["attachments"] = attachments
    return snapshot


def _compute_task_seed(attempt: VariantAttempt, variant_task: VariantTask) -> int:
    base = f"{attempt.assignment_id}:{attempt.id}:{variant_task.id}:{attempt.attempt_number}"
    digest = hashlib.sha256(base.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def _sum_logged_duration(attempt: VariantAttempt, variant_task: VariantTask) -> timedelta | None:
    qs = VariantTaskTimeLog.objects.filter(
        variant_attempt=attempt,
        variant_task=variant_task,
        duration__isnull=False,
    ).values_list("duration", flat=True)
    total = timedelta(0)
    for item in qs:
        total += item
    return total if total != timedelta(0) else None


def _get_time_spent_map(attempt: VariantAttempt) -> dict[int, timedelta]:
    totals = (
        VariantTaskTimeLog.objects.filter(
            variant_attempt=attempt,
            duration__isnull=False,
        )
        .values("variant_task_id")
        .annotate(total=Sum("duration"))
    )
    return {row["variant_task_id"]: row["total"] for row in totals if row["total"]}


def _should_track_time(attempt: VariantAttempt) -> bool:
    return bool(attempt.assignment.template.time_limit)


def _apply_attempt_timeout(attempt: VariantAttempt, *, now=None) -> bool:
    time_limit = attempt.assignment.template.time_limit
    if not time_limit or attempt.completed_at is not None:
        return False
    now = now or timezone.now()
    if now - attempt.started_at <= time_limit:
        return False
    _stop_active_task_timer(
        attempt,
        reason=VariantTaskTimeLog.StopReason.ATTEMPT_TIMEOUT,
        now=now,
        auto=True,
    )
    attempt.time_spent = time_limit
    attempt.mark_completed()
    return True


def _stop_active_task_timer(
    attempt: VariantAttempt,
    *,
    reason: str,
    now=None,
    only_if_task: VariantTask | None = None,
    auto: bool = False,
) -> None:
    if not _should_track_time(attempt):
        return
    if attempt.active_variant_task_id is None or attempt.active_started_at is None:
        return
    if only_if_task and attempt.active_variant_task_id != only_if_task.id:
        return

    now = now or timezone.now()
    start_ts = attempt.active_started_at
    duration = now - start_ts
    VariantTaskTimeLog.objects.create(
        variant_attempt=attempt,
        variant_task_id=attempt.active_variant_task_id,
        started_at=start_ts,
        stopped_at=now,
        duration=duration,
        stop_reason=reason,
        auto_stopped=auto,
    )
    attempt.active_variant_task = None
    attempt.active_started_at = None
    attempt.save(update_fields=["active_variant_task", "active_started_at", "updated_at"])


def _start_task_timer(attempt: VariantAttempt, variant_task: VariantTask, *, now=None) -> None:
    if not _should_track_time(attempt):
        return
    now = now or timezone.now()
    attempt.active_variant_task = variant_task
    attempt.active_started_at = now
    attempt.save(update_fields=["active_variant_task", "active_started_at", "updated_at"])


@transaction.atomic
def clear_task_response(
    user,
    attempt_id: int,
    variant_task_id: int,
) -> VariantTaskAttempt:
    """Remove saved draft answer for a task and restart its timer."""

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
            raise exceptions.ValidationError("Unable to prepare task snapshot for clearing the answer.")

    now = timezone.now()
    _stop_active_task_timer(
        attempt,
        reason=VariantTaskTimeLog.StopReason.CLEAR,
        now=now,
        auto=False,
    )

    snapshot = deepcopy(generation_attempt.task_snapshot or {})
    if "response" in snapshot:
        snapshot.pop("response", None)
    generation_attempt.task_snapshot = snapshot
    generation_attempt.save(update_fields=["task_snapshot", "updated_at"])

    _start_task_timer(attempt, variant_task, now=now)
    return generation_attempt


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

    now = timezone.now()
    _stop_active_task_timer(
        attempt,
        reason=VariantTaskTimeLog.StopReason.SAVE,
        now=now,
        only_if_task=variant_task,
    )

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

    now = timezone.now()
    _stop_active_task_timer(
        attempt,
        reason=VariantTaskTimeLog.StopReason.SUBMIT,
        now=now,
        only_if_task=variant_task,
    )

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
                "scoring_scheme": variant_task.task.get_scoring_scheme(),
                "max_score": variant_task.task.get_max_score(),
            }
        }

    task_payload = snapshot.get("task")
    scoring_scheme, max_score = _resolve_scoring(
        variant_task.task, task_payload if isinstance(task_payload, Mapping) else None
    )

    response_value = None
    if task_snapshot and isinstance(task_snapshot, Mapping):
        for key in ("value", "answer", "text"):
            if key in task_snapshot:
                response_value = task_snapshot.get(key)
                break
    correct_answer = None
    if isinstance(task_payload, Mapping):
        correct_answer = deepcopy(task_payload.get("correct_answer"))
    if correct_answer is None and variant_task.task:
        correct_answer = deepcopy(variant_task.task.correct_answer or {})

    computed_score = None
    computed_is_correct = None
    if correct_answer is not None and response_value is not None:
        computed_score, computed_is_correct = _grade_answer(
            scoring_scheme,
            correct_answer,
            response_value,
            max_score=max_score,
        )
    final_is_correct = is_correct if computed_is_correct is None else bool(computed_is_correct)
    time_spent = _sum_logged_duration(attempt, variant_task)

    task_attempt = VariantTaskAttempt.objects.create(
        variant_attempt=attempt,
        variant_task=variant_task,
        task=variant_task.task,
        attempt_number=next_number,
        is_correct=final_is_correct,
        score=computed_score,
        max_score=max_score,
        task_snapshot=snapshot,
        time_spent=time_spent,
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
    _stop_active_task_timer(
        attempt,
        reason=VariantTaskTimeLog.StopReason.FINALIZE,
        now=timezone.now(),
        auto=True,
    )

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

        scoring_scheme, max_score = _resolve_scoring(
            task, task_snapshot if isinstance(task_snapshot, Mapping) else None
        )
        computed_score: int | None = None
        computed_is_correct: bool | None = None
        if correct_answer is not None and response_value is not None:
            computed_score, computed_is_correct = _grade_answer(
                scoring_scheme,
                correct_answer,
                response_value,
                max_score=max_score,
            )
        time_spent = _sum_logged_duration(attempt, variant_task)

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
            submission.score = computed_score
            submission.max_score = max_score
            submission.task_snapshot = updated_snapshot
            submission.time_spent = time_spent
            submission.save(
                update_fields=["is_correct", "score", "max_score", "task_snapshot", "time_spent", "updated_at"]
            )
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
                score=computed_score,
                max_score=max_score,
                task_snapshot=record_snapshot,
                time_spent=time_spent,
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
        attempt = (
            VariantAttempt.objects.select_related("assignment__template")
            .prefetch_related(TASK_ATTEMPTS_PREFETCH, ASSIGNMENT_TEMPLATE_PREFETCH)
            .get(pk=attempt_id, assignment__user=user)
        )
    except VariantAttempt.DoesNotExist as exc:
        raise exceptions.NotFound("Attempt does not exist or is unavailable.") from exc
    _apply_attempt_timeout(attempt)
    return attempt


@transaction.atomic
def heartbeat_attempt(
    user,
    attempt_id: int,
    *,
    client_id=None,
) -> VariantAttempt:
    try:
        attempt = (
            VariantAttempt.objects.select_for_update()
            .select_related("assignment__template")
            .get(pk=attempt_id, assignment__user=user)
        )
    except VariantAttempt.DoesNotExist as exc:
        raise exceptions.NotFound("Attempt does not exist or is unavailable.") from exc

    now = timezone.now()
    update_fields = ["last_seen_at", "updated_at"]
    attempt.last_seen_at = now
    if client_id and attempt.active_client_id != client_id:
        attempt.active_client_id = client_id
        update_fields.append("active_client_id")
    attempt.save(update_fields=update_fields)
    _apply_attempt_timeout(attempt, now=now)
    return attempt


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
    template_tasks = list(
        attempt.assignment.template.template_tasks.select_related("task__type").prefetch_related(
            "task__attachments"
        ).all()
    )
    attempts_map: dict[int, list[VariantTaskAttempt]] = {}
    for task_attempt in attempt.task_attempts.all():
        attempts_map.setdefault(task_attempt.variant_task_id, []).append(task_attempt)
    time_spent_map = _get_time_spent_map(attempt)

    progress = []
    for variant_task in template_tasks:
        task_type_name = None
        answer_schema = None
        rendering_strategy = None
        task_body_html = ""
        max_score = None
        attachments = []
        if variant_task.task and variant_task.task.type:
            task_type_name = variant_task.task.type.name
        if variant_task.task:
            rendering_strategy = variant_task.task.rendering_strategy
            max_score = variant_task.task.get_max_score()
            attachments = _build_task_attachments_payload(variant_task.task)
        if variant_task.task:
            schema = variant_task.task.get_answer_schema()
            if schema:
                answer_schema = {
                    "id": schema.id,
                    "name": schema.name,
                    "config": schema.config or {},
                }
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
        aggregated_time = time_spent_map.get(variant_task.id)
        if generated_snapshot:
            rendering_strategy = (
                generated_snapshot.get("rendering_strategy")
                or rendering_strategy
            )
            if attachments and "attachments" not in generated_snapshot:
                generated_snapshot["attachments"] = deepcopy(attachments)
            desc = (
                generated_snapshot.get("description")
                or generated_snapshot.get("content", {}).get("statement")
                or ""
            )
            if desc:
                task_body_html = _render_task_body(desc, rendering_strategy)

        progress.append(
            {
                "variant_task_id": variant_task.id,
                "task_id": variant_task.task_id,
                "order": variant_task.order,
                "task_type_name": task_type_name,
                "answer_schema": answer_schema,
                "task_rendering_strategy": rendering_strategy,
                "task_body_html": task_body_html,
                "max_score": max_score,
                "max_attempts": variant_task.max_attempts,
                "attempts": actual_attempts,
                "attempts_used": len(actual_attempts),
                "is_completed": any(attempt.is_correct for attempt in actual_attempts),
                "task_snapshot": deepcopy(generated_snapshot) if generated_snapshot else None,
                "saved_response": deepcopy(saved_response) if saved_response is not None else None,
                "saved_response_updated_at": saved_response_updated_at,
                "time_spent": aggregated_time,
            }
        )

    progress.sort(key=lambda item: item["order"])
    return progress
