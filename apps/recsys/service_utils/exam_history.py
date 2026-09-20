"""Annual history and immutable reports, separate from live readiness."""
from collections import Counter
from copy import deepcopy

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, Max, Sum
from django.utils import timezone

from apps.recsys.models import Attempt, ExamProgressSnapshot, Task, TaskPlacement, TypeMastery, VariantTask, TrainingSessionStep
from .exam_context import identity_context, resolve_placement


def attempt_history(user, exam, *, since=None, until=None):
    """Calendar limits affect factual history, never the current readiness denominator."""
    attempts = Attempt.objects.filter(user=user, exam_version=exam)
    if since:
        attempts = attempts.filter(created_at__gte=since)
    if until:
        attempts = attempts.filter(created_at__lt=until)
    names = {}
    for type_id, context in attempts.order_by("created_at", "pk").values_list("task_type_id", "context_snapshot"):
        if context.get("task_type_name"):
            names.setdefault(type_id, context["task_type_name"])
    rows = []
    for row in attempts.values("task_type_id", "task_type__name").annotate(
        attempts=Count("pk"), valid=Count("pk", filter=Q(is_valid_attempt=True)),
        correct=Count("pk", filter=Q(is_valid_attempt=True, is_correct=True)), score_sum=Sum("score"), time_spent=Sum("time_spent"),
    ).order_by("task_type__display_order", "task_type_id"):
        rows.append({"type_id": row["task_type_id"], "name": names.get(row["task_type_id"], row["task_type__name"] or "Неизвестный тип"),
                     "attempts": row["attempts"], "valid": row["valid"], "correct": row["correct"], "score_sum": row["score_sum"],
                     "time_spent_seconds": row["time_spent"].total_seconds() if row["time_spent"] is not None else None})
    return {"types": rows, "since": since.isoformat() if since else None, "until": until.isoformat() if until else None}


def exam_report(user, exam, *, as_of=None):
    from .type_progress import build_type_progress_map
    now = as_of or timezone.now()
    types = list(exam.task_types.prefetch_related("required_tags"))
    progress = build_type_progress_map(user=user, task_type_ids=[t.pk for t in types], as_of=now)
    attempts = Attempt.objects.filter(user=user, exam_version=exam, created_at__lte=now, is_valid_attempt=True)
    counts = {r["task_type_id"]: r for r in attempts.values("task_type_id").annotate(total=Count("pk"), correct=Count("pk", filter=Q(is_correct=True)))}
    result = {}
    for task_type in types:
        info = progress[task_type.pk]
        result[str(task_type.pk)] = {
            "name": task_type.name, "display_order": task_type.display_order,
            "attempts": counts.get(task_type.pk, {}).get("total", 0),
            "correct": counts.get(task_type.pk, {}).get("correct", 0),
            "previous_year_evidence": info.previous_year_evidence,
            "readiness": info.effective_mastery, "coverage": info.coverage_ratio,
            "requirements": [{"tag_id": e.tag.pk, "name": e.tag.name, "solved": e.solved_count,
                              "bank_size": e.total_count, "progress": e.ratio} for e in info.tag_progress],
        }
    return {"version": 1, "exam_id": exam.pk, "exam_name": exam.name,
            "as_of": now.isoformat(), "types": result,
            "context_origins": dict(Counter(attempts.values_list("context_origin", flat=True)))}


@transaction.atomic
def capture_progress(user, exam, *, purpose="archive", as_of=None):
    from django.contrib.auth import get_user_model
    get_user_model().objects.select_for_update().get(pk=user.pk)
    now = as_of or timezone.now()
    data = exam_report(user, exam, as_of=now)
    return ExamProgressSnapshot.objects.get_or_create(user=user, exam_version=exam, purpose=purpose, as_of=now, defaults={"data": data})[0]


def backfill_context(*, apply=False, batch_size=500):
    """No calls to Attempt.save/signals: existing evidence must not be replayed."""
    report = Counter()
    issues = []
    if apply:
        # Preserve stored legacy estimates before a subsequent rebuild can alter them.
        for user_id, exam_id in TypeMastery.objects.exclude(task_type__exam_version=None).values_list("user_id", "task_type__exam_version_id").distinct():
            if not ExamProgressSnapshot.objects.filter(user_id=user_id, exam_version_id=exam_id, purpose="before_backfill").exists():
                rows = list(TypeMastery.objects.filter(user_id=user_id, task_type__exam_version_id=exam_id).values())
                for row in rows:
                    for key, value in row.items():
                        if hasattr(value, "isoformat"):
                            row[key] = value.isoformat()
                ExamProgressSnapshot.objects.create(user_id=user_id, exam_version_id=exam_id, purpose="before_backfill", algorithm_version="legacy-stored-v1", data={"legacy_type_masteries": rows})
    for task in Task.objects.select_related("type__exam_version", "exam_version").iterator(chunk_size=batch_size):
        if task.type.exam_version_id and task.exam_version_id not in (None, task.type.exam_version_id):
            report["conflicting_tasks"] += 1
            issues.append({"task_id": task.pk, "reason": "task/type exam mismatch"})
        elif task.type.exam_version_id:
            if not TaskPlacement.objects.filter(task=task, task_type=task.type).exists():
                report["placements_missing"] += 1
                if apply:
                    TaskPlacement.objects.get_or_create(task=task, task_type=task.type)
        else:
            report["tasks_without_annual_type"] += 1
    upper_bound = Attempt.objects.aggregate(pk=Max("pk"))["pk"] or 0
    qs = Attempt.objects.filter(context_origin="unknown", pk__lte=upper_bound).select_related("task__type__exam_version", "task__exam_version", "variant_task_attempt__variant_attempt__assignment__template__exam_version")
    for attempt in qs.iterator(chunk_size=batch_size):
        try:
            source = None
            snapshot = {}
            context = None
            origin = "inferred"
            exam = None
            if attempt.variant_task_attempt_id:
                source = attempt.variant_task_attempt
                raw = source.task_snapshot or {}
                snapshot = deepcopy(raw.get("task", raw))
                context = snapshot.get("context")
                exam = source.variant_attempt.assignment.template.exam_version
                if context:
                    origin = "snapshot"
            if not source:
                step = TrainingSessionStep.objects.filter(attempt=attempt).select_related("session__exam_version").first()
                if step:
                    snapshot = deepcopy(step.task_snapshot)
                    context = snapshot.get("context")
                    exam = step.session.exam_version
                    if context:
                        origin = "snapshot"
            if not context:
                task = attempt.task
                selected_exam = exam or task.type.exam_version or task.exam_version
                expected = task.type.exam_version_id or task.exam_version_id
                if selected_exam and expected != selected_exam.pk:
                    raise ValueError("Historical exam conflicts with current task classification")
                if task.type.exam_version_id and task.exam_version_id not in (None, task.type.exam_version_id):
                    raise ValueError("Task/type exam mismatch")
                placement = TaskPlacement.objects.filter(task=task, task_type=task.type).first()
                context = identity_context(task, placement, exam_version=selected_exam)
                context["inferred_fields"] = ["task_type_id", "tag_ids", "skill_ids", "level_band", "expected_time_seconds"]
                context["exam_origin"] = "session" if exam else "inferred"
            report[origin] += 1
            if apply:
                Attempt.objects.filter(pk=attempt.pk, context_origin="unknown").update(
                    placement_id=context.get("placement_id"), exam_version_id=context.get("exam_version_id"),
                    task_type_id=context.get("task_type_id"), context_snapshot=context, task_snapshot=snapshot,
                    context_origin=origin,
                )
        except (ValueError, ValidationError) as exc:
            # Preserve the event and report it for manual review; no guessing on conflict.
            report["unresolved"] += 1
            issues.append({"attempt_id": attempt.pk, "reason": str(exc)})
    if apply:
        for row in VariantTask.objects.filter(placement=None).select_related("task__type", "template__exam_version").iterator(chunk_size=batch_size):
            placement = TaskPlacement.objects.filter(task=row.task, task_type=row.task.type).first()
            if placement and row.template.exam_version_id == placement.task_type.exam_version_id:
                VariantTask.objects.filter(pk=row.pk).update(placement=placement)
    from .legacy_issuance import backfill_issued_work
    report.update(backfill_issued_work(apply=apply, batch_size=batch_size))
    return {"apply": apply, "attempt_upper_bound": upper_bound, "counts": dict(report), "issues": issues}
