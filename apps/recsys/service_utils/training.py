from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from typing import Any, Mapping

from django.db import transaction
from django.utils import timezone
from rest_framework import exceptions

from apps.recsys.models import (
    Attempt,
    RecommendationLog,
    TrainingSession,
    TrainingSessionStep,
    Task,
    TaskType,
)
from apps.recsys.presentation.tasks import build_task_statement_payload
from apps.recsys.recommendation import (
    RecommendationCandidate,
    mark_recommendation_opened,
    recommend_task_candidates,
)
from .grading import grade_answer
from .training_type_filters import (
    build_type_filter_payload,
    validate_selected_task_type_ids,
)


def _task_snapshot(task: Task) -> dict[str, Any]:
    statement = build_task_statement_payload(task=task)
    schema = task.get_answer_schema()
    answer_schema = None
    if schema is not None:
        answer_schema = {
            "id": schema.id,
            "name": schema.name,
            "config": schema.config or {},
        }
    return {
        "task_id": task.id,
        "title": statement["title"],
        "description": statement["description"],
        "rendering_strategy": statement["task_rendering_strategy"],
        "task_body_html": statement["task_body_html"],
        "image": statement["image"],
        "attachments": statement["attachments"],
        "answer_schema": answer_schema,
        "correct_answer": deepcopy(task.correct_answer or {}),
        "scoring_scheme": task.get_scoring_scheme(),
        "max_score": task.get_max_score(),
        "task_type_name": task.type.name if task.type_id else "",
    }


def _serialize_step(step: TrainingSessionStep) -> dict[str, Any]:
    task_snapshot = deepcopy(step.task_snapshot or {})
    response_snapshot = deepcopy(step.response_snapshot or {})
    return {
        "id": step.id,
        "order": step.order,
        "status": step.status,
        "result": step.result,
        "shown_at": step.shown_at,
        "answered_at": step.answered_at,
        "task_id": step.task_id,
        "task_title": task_snapshot.get("title") or (step.task.title if step.task else ""),
        "task_type_name": task_snapshot.get("task_type_name") or (step.task.type.name if step.task and step.task.type_id else ""),
        "task_snapshot": task_snapshot,
        "response_snapshot": response_snapshot,
        "reason_snapshot": deepcopy(step.reason_snapshot or {}),
    }


def _freshen_open_task_snapshot(step: TrainingSessionStep) -> dict[str, Any]:
    task_snapshot = deepcopy(step.task_snapshot or {})
    if step.task is None:
        return task_snapshot

    fresh_snapshot = _task_snapshot(step.task)
    for key in (
        "title",
        "description",
        "rendering_strategy",
        "task_body_html",
        "image",
        "attachments",
        "answer_schema",
        "max_score",
        "task_type_name",
    ):
        if key in {"task_body_html", "image", "attachments"} or not task_snapshot.get(key):
            task_snapshot[key] = deepcopy(fresh_snapshot.get(key))
    return task_snapshot


def _session_summary(session: TrainingSession) -> dict[str, Any]:
    accuracy = (
        (session.correct_steps / session.completed_steps)
        if session.completed_steps
        else 0.0
    )
    return {
        "id": session.id,
        "status": session.status,
        "started_at": session.started_at,
        "last_activity_at": session.last_activity_at,
        "ended_at": session.ended_at,
        "selected_task_type_ids": list(session.selected_task_type_ids or []),
        "steps_total": session.steps_total,
        "completed_steps": session.completed_steps,
        "correct_steps": session.correct_steps,
        "accuracy": accuracy,
    }


def get_current_session(user, *, exam_version_id: int) -> TrainingSession | None:
    return (
        TrainingSession.objects.filter(
            user=user,
            exam_version_id=exam_version_id,
            status=TrainingSession.Status.ACTIVE,
        )
        .prefetch_related("steps__task", "steps__recommendation_log", "steps__attempt")
        .order_by("-started_at", "-id")
        .first()
    )


def get_session_or_404(user, session_id: int) -> TrainingSession:
    try:
        return (
            TrainingSession.objects.filter(user=user)
            .prefetch_related("steps__task", "steps__recommendation_log", "steps__attempt")
            .get(pk=session_id)
        )
    except TrainingSession.DoesNotExist as exc:
        raise exceptions.NotFound("Training session not found.") from exc


def _pick_candidate_for_session(user, session: TrainingSession) -> RecommendationCandidate | None:
    used_task_ids = set(session.steps.values_list("task_id", flat=True))
    candidates = recommend_task_candidates(
        user,
        limit=50,
        log=False,
        source_mode=RecommendationLog.SourceMode.TRAINING,
        exam_version=session.exam_version,
        task_type_ids=session.selected_task_type_ids or None,
        exclude_recent=False,
        exclude_solved=True,
    )
    for candidate in candidates:
        if candidate.task.id not in used_task_ids:
            return candidate
    return None


def _create_recommendation_log(user, candidate: RecommendationCandidate) -> RecommendationLog:
    recommendation = RecommendationLog.objects.create(
        user=user,
        task=candidate.task,
        status=RecommendationLog.Status.RECOMMENDED,
        recommended_at=timezone.now(),
        source_mode=RecommendationLog.SourceMode.TRAINING,
        rank_position=1,
        score_snapshot=candidate.score_snapshot,
        reason_snapshot=candidate.reason_snapshot,
        weak_tags_snapshot=candidate.weak_tags_snapshot,
        coverage_gain_snapshot=candidate.coverage_gain_snapshot,
        spacing_gain_snapshot=candidate.spacing_gain_snapshot,
        completed=False,
    )
    return recommendation


def _append_next_step(user, session: TrainingSession) -> TrainingSessionStep | None:
    candidate = _pick_candidate_for_session(user, session)
    if candidate is None:
        return None
    recommendation = _create_recommendation_log(user, candidate)
    mark_recommendation_opened(recommendation)
    step = TrainingSessionStep.objects.create(
        session=session,
        order=session.steps_total + 1,
        task=candidate.task,
        recommendation_log=recommendation,
        status=TrainingSessionStep.Status.OPENED,
        task_snapshot=_task_snapshot(candidate.task),
        reason_snapshot=deepcopy(candidate.reason_snapshot or {}),
        shown_at=timezone.now(),
    )
    session.steps_total = step.order
    session.last_activity_at = timezone.now()
    session.save(update_fields=["steps_total", "last_activity_at", "updated_at"])
    return step


def _selected_task_types_summary(session: TrainingSession) -> list[dict[str, Any]]:
    selected_ids = list(session.selected_task_type_ids or [])
    if not selected_ids:
        return []
    task_types = {
        task_type.id: task_type
        for task_type in TaskType.objects.filter(id__in=selected_ids)
    }
    summary = []
    for type_id in selected_ids:
        task_type = task_types.get(type_id)
        if task_type is None:
            continue
        summary.append(
            {
                "type_id": task_type.id,
                "type_name": task_type.name,
                "display_order": int(task_type.display_order or 0),
            }
        )
    return summary


@transaction.atomic
def start_session(user, *, exam_version, selected_task_type_ids: list[int] | None = None) -> TrainingSession:
    validated_type_ids = validate_selected_task_type_ids(
        exam_version=exam_version,
        selected_task_type_ids=selected_task_type_ids,
    )
    if not validated_type_ids:
        defaults = build_type_filter_payload(user=user, exam_version=exam_version)
        validated_type_ids = list(defaults.get("recommended_type_ids") or [])

    available_candidates = recommend_task_candidates(
        user,
        limit=1,
        log=False,
        source_mode=RecommendationLog.SourceMode.TRAINING,
        exam_version=exam_version,
        task_type_ids=validated_type_ids or None,
        exclude_recent=False,
        exclude_solved=True,
    )
    if not available_candidates:
        raise exceptions.ValidationError(
            {
                "selected_task_type_ids": (
                    "Для выбранных типов нет доступных новых опубликованных задач. "
                    "Выберите больше типов или вернитесь позже."
                )
            }
        )

    active = (
        TrainingSession.objects.select_for_update()
        .filter(
            user=user,
            exam_version=exam_version,
            status=TrainingSession.Status.ACTIVE,
        )
        .order_by("-started_at", "-id")
        .first()
    )
    if active is not None:
        active.mark_abandoned()

    session = TrainingSession.objects.create(
        user=user,
        exam_version=exam_version,
        status=TrainingSession.Status.ACTIVE,
        last_activity_at=timezone.now(),
        selected_task_type_ids=validated_type_ids,
    )
    if _append_next_step(user, session) is None:
        session.mark_completed()
    return get_session_or_404(user, session.id)


def _active_step(session: TrainingSession) -> TrainingSessionStep | None:
    for step in session.steps.all():
        if step.status in {
            TrainingSessionStep.Status.RECOMMENDED,
            TrainingSessionStep.Status.OPENED,
        }:
            return step
    return None


def session_payload(session: TrainingSession) -> dict[str, Any]:
    steps = list(session.steps.all().order_by("order", "id"))
    active_step = _active_step(session)
    current_task = None
    if active_step is not None:
        current_task = {
            "step_id": active_step.id,
            "order": active_step.order,
            "reason_snapshot": deepcopy(active_step.reason_snapshot or {}),
            **_freshen_open_task_snapshot(active_step),
        }

    return {
        "session": _session_summary(session),
        "selected_task_types": _selected_task_types_summary(session),
        "current_step": _serialize_step(active_step) if active_step else None,
        "current_task": current_task,
        "history": [_serialize_step(step) for step in steps],
    }


@transaction.atomic
def submit_step_answer(
    user,
    *,
    session_id: int,
    step_id: int,
    answer: Any,
) -> dict[str, Any]:
    session = (
        TrainingSession.objects.select_for_update()
        .filter(user=user)
        .prefetch_related("steps__task", "steps__recommendation_log", "steps__attempt")
        .get(pk=session_id)
    )
    if session.status != TrainingSession.Status.ACTIVE:
        raise exceptions.ValidationError("Training session is not active.")

    try:
        step = next(item for item in session.steps.all() if item.id == step_id)
    except StopIteration as exc:
        raise exceptions.ValidationError("Training step not found in this session.") from exc

    if step.status == TrainingSessionStep.Status.ANSWERED:
        raise exceptions.ValidationError("This training step has already been answered.")
    if step.task is None:
        raise exceptions.ValidationError("Training step has no task.")

    snapshot = deepcopy(step.task_snapshot or {})
    scoring_scheme = snapshot.get("scoring_scheme") or step.task.get_scoring_scheme()
    max_score = int(snapshot.get("max_score") or step.task.get_max_score() or 1)
    correct_answer = deepcopy(snapshot.get("correct_answer"))
    if correct_answer is None:
        correct_answer = deepcopy(step.task.correct_answer or {})

    score, is_correct = grade_answer(
        scoring_scheme,
        correct_answer,
        answer,
        max_score=max_score,
    )
    checked_at = timezone.now()
    time_spent = None
    if step.shown_at is not None:
        delta = checked_at - step.shown_at
        if delta.total_seconds() > 0:
            time_spent = delta

    attempt = Attempt.objects.create(
        user=user,
        task=step.task,
        is_correct=bool(is_correct),
        score=score,
        max_score=max_score,
        time_spent=time_spent,
        is_valid_attempt=True,
        mode=Attempt.Mode.TRAINING,
        checked_at=checked_at,
        source_recommendation=step.recommendation_log,
    )

    if score is None or max_score <= 0:
        result = TrainingSessionStep.Result.UNKNOWN
    elif score >= max_score:
        result = TrainingSessionStep.Result.CORRECT
    elif score > 0:
        result = TrainingSessionStep.Result.PARTIAL
    else:
        result = TrainingSessionStep.Result.INCORRECT

    step.attempt = attempt
    step.status = TrainingSessionStep.Status.ANSWERED
    step.result = result
    step.response_snapshot = {"answer": deepcopy(answer)}
    step.answered_at = checked_at
    step.save(
        update_fields=[
            "attempt",
            "status",
            "result",
            "response_snapshot",
            "answered_at",
            "updated_at",
        ]
    )

    session.completed_steps += 1
    if result == TrainingSessionStep.Result.CORRECT:
        session.correct_steps += 1
    session.last_activity_at = checked_at
    session.save(
        update_fields=[
            "completed_steps",
            "correct_steps",
            "last_activity_at",
            "updated_at",
        ]
    )

    next_step = _append_next_step(user, session)
    if next_step is None:
        session.mark_completed()
    refreshed = get_session_or_404(user, session.id)
    payload = session_payload(refreshed)
    payload["submission_result"] = {
        "step_id": step.id,
        "attempt_id": attempt.id,
        "is_correct": bool(is_correct),
        "score": score,
        "max_score": max_score,
        "result": result,
        "answer": deepcopy(answer),
        "correct_answer": correct_answer,
        "answered_at": checked_at,
    }
    payload["next_step_id"] = next_step.id if next_step else None
    return payload


@transaction.atomic
def end_session(user, *, session_id: int) -> TrainingSession:
    session = (
        TrainingSession.objects.select_for_update()
        .filter(user=user)
        .get(pk=session_id)
    )
    if session.status == TrainingSession.Status.ACTIVE:
        session.mark_completed()
    return get_session_or_404(user, session.id)
