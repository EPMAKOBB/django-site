"""Freeze the remaining legacy work using only preserved issued content.

Current configuration may establish a plausible identity, never an exact past
scale or statement. All reconstructed fields carry explicit provenance.
"""
from copy import deepcopy
from collections import Counter

from apps.recsys.models import VariantAttempt, VariantTaskAttempt, TrainingSessionStep
from apps.recsys.presentation.tasks import build_task_statement_payload, statement_fingerprint
from .exam_context import identity_context


def _freeze(payload, task, placement, exam, order, max_score=None):
    payload = deepcopy(payload or {})
    if payload.get("context"):
        return payload
    context = identity_context(task, placement, exam_version=exam, order=order)
    context.update(origin="inferred", inferred_fields=["task_type_id", "tag_ids", "skill_ids", "level_band", "expected_time_seconds"])
    payload["context"] = context
    payload["task_type_name"] = context["task_type_name"]
    if "max_score" not in payload and max_score is not None:
        payload["max_score"] = max_score
    # Do not render current Task fields over a saved old statement.
    statement = build_task_statement_payload(statement_source=payload)
    payload.update(task_body_html=statement["task_body_html"], image=statement["image"],
                   attachments=statement["attachments"], statement_fingerprint=statement_fingerprint(payload))
    return payload


def backfill_issued_work(*, apply=False, batch_size=500):
    counts = Counter()
    for attempt in VariantAttempt.objects.filter(exam_snapshot={}).select_related("assignment__template__exam_version").iterator(chunk_size=batch_size):
        template = attempt.assignment.template
        rows = list(attempt.task_attempts.select_related("task__type__exam_version", "variant_task__placement__task_type__exam_version").order_by("attempt_number", "pk"))
        manifest = {}
        for row in rows:
            if not row.task_id:
                continue
            raw = row.task_snapshot or {}
            payload = _freeze(raw.get("task", raw), row.task, row.variant_task.placement, template.exam_version,
                              row.variant_task.order, row.max_score)
            manifest.setdefault(row.variant_task_id, {"variant_task_id": row.variant_task_id, "task_id": row.task_id,
                                                      "order": row.variant_task.order, "max_score": payload.get("max_score", row.max_score),
                                                      "max_attempts": row.variant_task.max_attempts})
            if apply and not raw.get("task", raw).get("context"):
                updated = {"task": payload}
                if "response" in raw:
                    updated["response"] = deepcopy(raw["response"])
                VariantTaskAttempt.objects.filter(pk=row.pk).update(task_snapshot=updated)
        counts["legacy_work_snapshots"] += 1
        if apply:
            VariantAttempt.objects.filter(pk=attempt.pk, exam_snapshot={}).update(exam_snapshot={
                "version": 1, "origin": "inferred", "exam_version_id": template.exam_version_id,
                "exam_name": template.exam_version.name if template.exam_version else "",
                "template_name": template.name, "items": list(manifest.values()),
                "time_limit_seconds": template.time_limit.total_seconds() if template.time_limit else None,
                "scale": None, "scale_unknown": True,
                "inferred_fields": ["template_name", "time_limit_seconds", "order", "max_attempts"],
                "composition_complete": len(manifest) == template.template_tasks.count(),
            })
    for step in TrainingSessionStep.objects.filter(task__isnull=False).select_related("task__type__exam_version", "placement__task_type__exam_version", "session__exam_version").iterator(chunk_size=batch_size):
        if (step.task_snapshot or {}).get("context"):
            continue
        counts["legacy_training_snapshots"] += 1
        if apply:
            TrainingSessionStep.objects.filter(pk=step.pk).update(task_snapshot=_freeze(step.task_snapshot, step.task, step.placement,
                                                                                      step.session.exam_version, step.order))
    return counts
