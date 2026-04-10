from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Max
from django.utils import timezone

from apps.recsys.models import Attempt, TaskType
from apps.recsys.service_utils.type_progress import build_type_progress_map

SUMMARY_TEXT = (
    "Мы рекомендуем типы, которые сейчас лучше всего подходят для прогресса: "
    "закрывают слабые места, недавние пробелы и типы с недостаточной практикой."
)


def validate_selected_task_type_ids(*, exam_version, selected_task_type_ids) -> list[int]:
    raw_ids = selected_task_type_ids or []
    if not raw_ids:
        return []

    normalized: list[int] = []
    seen: set[int] = set()
    for item in raw_ids:
        try:
            type_id = int(item)
        except (TypeError, ValueError) as exc:
            raise ValueError("Each selected task type id must be an integer.") from exc
        if type_id <= 0:
            raise ValueError("Each selected task type id must be positive.")
        if type_id in seen:
            continue
        seen.add(type_id)
        normalized.append(type_id)

    allowed_ids = set(
        TaskType.objects.filter(exam_version=exam_version).values_list("id", flat=True)
    )
    invalid_ids = [type_id for type_id in normalized if type_id not in allowed_ids]
    if invalid_ids:
        raise ValueError("Selected task types must belong to the same exam version.")
    return normalized


def _recent_activity_map(user, *, task_type_ids: list[int]) -> dict[int, dict]:
    rows = (
        Attempt.objects.filter(
            user=user,
            task__type_id__in=task_type_ids,
            is_valid_attempt=True,
        )
        .values("task__type_id")
        .annotate(
            attempts_total=Count("id"),
            last_checked_at=Max("checked_at"),
        )
    )
    return {
        int(row["task__type_id"]): {
            "attempts_total": int(row["attempts_total"] or 0),
            "last_checked_at": row["last_checked_at"],
        }
        for row in rows
    }


def _clamp_unit(value: float | None) -> float:
    if value is None:
        return 0.0
    return max(0.0, min(1.0, float(value)))


def _reason_for_type(*, progress, attempts_total: int, last_checked_at):
    weak_tags = [
        entry.tag.name
        for entry in sorted(progress.tag_progress, key=lambda item: item.ratio)[:2]
        if entry.total_count > 0 and entry.ratio < 0.75
    ]
    if weak_tags:
        return (
            "weak_tags",
            f"Слабые темы: {', '.join(weak_tags)}",
            weak_tags,
        )

    coverage_gap = 1.0 - progress.coverage_ratio
    if coverage_gap >= 0.35:
        return ("low_coverage", "Тип недоработан по покрытию.", [])

    if attempts_total <= 1:
        return ("low_recent_practice", "Пока мало практики по этому типу.", [])

    if last_checked_at is None or last_checked_at <= timezone.now() - timedelta(days=10):
        return ("review_needed", "Давно не было недавней практики.", [])

    if progress.effective_mastery < 0.55:
        return ("good_next_step", "Подходит как следующий шаг по текущему уровню.", [])

    return ("review_needed", "Полезно повторить для закрепления.", [])


def build_type_filter_payload(*, user, exam_version, recommended_limit: int = 4) -> dict:
    task_types = list(
        TaskType.objects.filter(exam_version=exam_version).prefetch_related("required_tags")
    )
    type_ids = [task_type.id for task_type in task_types]
    progress_map = build_type_progress_map(user=user, task_type_ids=type_ids)
    recent_map = _recent_activity_map(user, task_type_ids=type_ids)

    scored_types: list[dict] = []
    now = timezone.now()
    for task_type in task_types:
        progress = progress_map.get(task_type.id)
        if progress is None:
            continue
        recent = recent_map.get(task_type.id, {})
        attempts_total = int(recent.get("attempts_total") or 0)
        last_checked_at = recent.get("last_checked_at")
        if last_checked_at is None:
            spacing_gap = 1.0
        else:
            days_since = max(0.0, (now - last_checked_at).total_seconds() / 86400.0)
            spacing_gap = _clamp_unit(days_since / 14.0)

        mastery_gap = _clamp_unit(1.0 - progress.effective_mastery)
        coverage_gap = _clamp_unit(1.0 - progress.coverage_ratio)
        novelty_gap = 1.0 / (1.0 + attempts_total)
        score = (
            0.45 * mastery_gap
            + 0.30 * coverage_gap
            + 0.15 * spacing_gap
            + 0.10 * novelty_gap
        )
        reason_code, reason_summary, weak_tags = _reason_for_type(
            progress=progress,
            attempts_total=attempts_total,
            last_checked_at=last_checked_at,
        )
        scored_types.append(
            {
                "type_id": task_type.id,
                "type_name": task_type.name,
                "display_order": int(task_type.display_order or 0),
                "score": score,
                "reason_code": reason_code,
                "reason_summary": reason_summary,
                "weak_tags": weak_tags,
                "attempts_total": attempts_total,
                "last_checked_at": last_checked_at,
            }
        )

    scored_types.sort(key=lambda item: (item["score"], -item["display_order"], -item["type_id"]), reverse=True)
    recommended_type_ids = [item["type_id"] for item in scored_types[:recommended_limit]]

    types_payload = []
    for item in sorted(scored_types, key=lambda entry: (entry["display_order"], entry["type_name"])):
        is_recommended = item["type_id"] in recommended_type_ids
        types_payload.append(
            {
                "type_id": item["type_id"],
                "type_name": item["type_name"],
                "display_order": item["display_order"],
                "recommended": is_recommended,
                "selected_by_default": is_recommended,
                "reason_code": item["reason_code"],
                "reason_summary": item["reason_summary"] if is_recommended else "",
                "weak_tags": item["weak_tags"] if is_recommended else [],
            }
        )

    if not recommended_type_ids:
        recommended_type_ids = [item["type_id"] for item in types_payload[:recommended_limit]]
        for item in types_payload:
            if item["type_id"] in recommended_type_ids:
                item["recommended"] = True
                item["selected_by_default"] = True
                if not item["reason_summary"]:
                    item["reason_code"] = "good_next_step"
                    item["reason_summary"] = "Подходит как следующий шаг по текущему уровню."

    return {
        "summary": SUMMARY_TEXT,
        "recommended_type_ids": recommended_type_ids,
        "types": types_payload,
    }
