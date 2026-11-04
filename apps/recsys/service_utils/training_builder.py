"""Persistent exam-scoped selection and lifecycle of ordinary variant works."""
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Count, OuterRef, Subquery
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from rest_framework import exceptions

from apps.recsys.models import (
    ExamVersion, Task, TaskType, TrainingDraft, VariantAssignment, VariantAttempt,
    VariantTask, VariantTemplate, VariantTaskAttempt,
)
from apps.recsys.recommendation import recommend_task_candidates
from .exam_context import ensure_exam_available, resolve_placement, task_filter
from .publication import public_tasks_queryset
from . import variants
from . import training_lifecycle as lifecycle

MAX_TASKS = 100


class DraftConflict(exceptions.APIException):
    status_code = 409
    default_detail = "Состав изменился в другой вкладке. Обновили данные; повторите действие."


def available_tasks(exam):
    return public_tasks_queryset().filter(task_filter(exam_version=exam, for_issuance=True)).exclude(
        is_dynamic=True, dynamic_mode=Task.DynamicMode.PRE_GENERATED, pregenerated_datasets__isnull=True,
    ).distinct()


def _available(exam):
    try:
        ensure_exam_available(exam)
    except DjangoValidationError as exc:
        raise exceptions.ValidationError(exc.messages) from exc


def _catalog(exam):
    rows = {}
    for task in available_tasks(exam).select_related("type__exam_version").prefetch_related("tags", "placements__task_type__exam_version"):
        placements = [p for p in task.placements.all() if p.status == "active" and p.task_type.exam_version_id == exam.pk]
        # A concrete type is part of each selection; task IDs remain unique in a variant.
        for type_id in ([p.task_type_id for p in placements] or [task.type_id]):
            rows[(task.pk, type_id)] = task
    return rows


def _ranked(user, exam, type_id=None, *, exclude_solved=False):
    return recommend_task_candidates(user, exam_version=exam, task_type_ids=[type_id] if type_id else None,
                                     exclude_recent=False, exclude_solved=exclude_solved, log=False)


def _selection(task, type_id, *, manual=False, reason="Подобрано по вашему прогрессу"):
    return {"task_id": task.pk, "type_id": type_id, "manual": manual, "reason": reason}


def _reason(candidate):
    tags = candidate.reason_snapshot.get("top_weak_tags", [])
    if tags:
        return "Для практики: " + ", ".join(tag["tag_name"] for tag in tags[:2])
    return "Подобрано по вашему прогрессу"


def _sync_counts(draft):
    counts = Counter(s["type_id"] for s in draft.selections)
    for type_id, count in counts.items():
        setting = draft.type_settings.setdefault(str(type_id), {"tags": {}})
        setting["count"] = max(setting.get("count", 0), count)


def draft_payload(draft):
    catalog = _catalog(draft.exam_version)
    selections = []
    for entry in draft.selections:
        task = catalog.get((entry["task_id"], entry["type_id"]))
        selections.append({**entry, "title": task.title if task else "Задание больше недоступно",
                           "available": task is not None,
                           "tag_ids": [t.pk for t in task.tags.all()] if task else []})
    counts = Counter(row["type_id"] for row in selections)
    types = []
    for task_type in TaskType.objects.filter(exam_version=draft.exam_version).prefetch_related("required_tags").order_by("display_order", "id"):
        tasks = {pk: task for (pk, tid), task in catalog.items() if tid == task_type.pk}
        tags = {tag.pk: tag for task in tasks.values() for tag in task.tags.all()}
        tags.update({tag.pk: tag for tag in task_type.required_tags.all()})
        settings = draft.type_settings.get(str(task_type.pk), {})
        selected = [s for s in selections if s["type_id"] == task_type.pk]
        types.append({"id": task_type.pk, "name": task_type.name, "count": counts[task_type.pk],
                      "requested": settings.get("count", counts[task_type.pk]), "available": len(tasks),
                      "tags": [{"id": pk, "name": tag.name,
                                "count": sum(pk in s["tag_ids"] for s in selected),
                                "minimum": settings.get("tags", {}).get(str(pk), 0),
                                "available": sum(pk in [t.pk for t in task.tags.all()] for task in tasks.values())}
                               for pk, tag in sorted(tags.items(), key=lambda pair: pair[1].name)]})
    current = lifecycle.current_training(draft.user, draft.exam_version).values_list("pk", flat=True).first()
    return {"revision": draft.revision, "lifecycle_revision": draft.lifecycle_revision,
            "current_attempt_id": current, "exam_version_id": draft.exam_version_id,
            "current_attempt_url": reverse("accounts:variant-attempt-solver", args=[current]) if current else None,
            "selections": selections, "count": len(selections), "types": types}


def get_draft(user, exam):
    return TrainingDraft.objects.get_or_create(user=user, exam_version=exam)[0]


def _set_count(draft, user, catalog, type_id, count, minima):
    if not TaskType.objects.filter(pk=type_id, exam_version=draft.exam_version).exists():
        raise exceptions.ValidationError("Тип не относится к этому экзамену.")
    pool = {pk: task for (pk, tid), task in catalog.items() if tid == type_id}
    valid_tags = {tag.pk for task in pool.values() for tag in task.tags.all()}
    valid_tags.update(TaskType.objects.get(pk=type_id).required_tags.values_list("pk", flat=True))
    if any(int(pk) not in valid_tags or value > count for pk, value in minima.items()):
        raise exceptions.ValidationError("Проверьте теги и их количество: минимум не может превышать число задач типа.")
    others = [s for s in draft.selections if s["type_id"] != type_id]
    old = [s for s in draft.selections if s["type_id"] == type_id and s["task_id"] in pool]
    locked = [s for s in old if s["manual"]]
    if count < len(locked):
        raise exceptions.ValidationError(f"Вручную выбрано {len(locked)} задач. Снимите лишние галочки в составе или на странице типа.")
    used_elsewhere = {s["task_id"] for s in others}
    ranked = _ranked(user, draft.exam_version, type_id)
    reasons = {c.task.pk: _reason(c) for c in ranked}
    order = [s["task_id"] for s in old] + [c.task.pk for c in ranked]
    order = list(dict.fromkeys(order))
    order += [pk for pk in pool if pk not in order]
    tags = {pk: {t.pk for t in task.tags.all()} for pk, task in pool.items()}
    chosen = list(locked)
    while len(chosen) < count:
        selected_ids = {s["task_id"] for s in chosen}
        deficits = {int(pk) for pk, minimum in minima.items()
                    if sum(int(pk) in tags[s["task_id"]] for s in chosen) < minimum}
        options = [pk for pk in order if pk not in selected_ids and pk not in used_elsewhere]
        if not options:
            break
        best = max(options, key=lambda pk: len(tags[pk] & deficits))
        chosen.append(next((s for s in old if s["task_id"] == best), _selection(pool[best], type_id, reason=reasons.get(best, "Подобрано по выбранным условиям"))))
    if len(others) + len(chosen) > MAX_TASKS:
        raise exceptions.ValidationError(f"В одной тренировке можно выбрать до {MAX_TASKS} задач.")
    draft.selections = others + chosen
    draft.type_settings[str(type_id)] = {"count": count, "tags": minima}


@transaction.atomic
def change_draft(user, exam, data):
    lifecycle.lock_user(user)
    fingerprint = lifecycle.operation_fingerprint({"exam": exam.pk, **data})
    previous = lifecycle.replay(user, data.get("operation_id"), fingerprint)
    if previous is not None:
        return previous
    _available(exam)
    draft = get_draft(user, exam)
    if data["revision"] != draft.revision:
        raise DraftConflict()
    action = data["action"]
    if lifecycle.current_training(user, exam).exists():
        raise lifecycle.TrainingConflict("Сначала отправьте текущую тренировку в архив.")
    if action == "start" and data.get("lifecycle_revision", draft.lifecycle_revision) != draft.lifecycle_revision:
        raise lifecycle.TrainingConflict()
    catalog = _catalog(exam)
    if action == "start":
        if len(draft.selections) > MAX_TASKS or len({s["task_id"] for s in draft.selections}) != len(draft.selections):
            raise exceptions.ValidationError("В тренировке допускается до 100 разных задач.")
        window = getattr(settings, "TRAINING_CREATE_WINDOW_SECONDS", 600)
        limit = getattr(settings, "TRAINING_CREATE_LIMIT", 10)
        if VariantAttempt.objects.filter(assignment__user=user, mode="training", started_at__gte=timezone.now() - timedelta(seconds=window)).count() >= limit:
            raise exceptions.Throttled(wait=window, detail="Слишком много новых тренировок. Продолжите одну из сохранённых или попробуйте позже.")
        if not draft.selections:
            raise exceptions.ValidationError("Добавьте хотя бы одну задачу.")
        if any((s["task_id"], s["type_id"]) not in catalog for s in draft.selections):
            raise exceptions.ValidationError("В составе есть недоступные задачи. Удалите их перед запуском.")
        base_name = f"Тренировка {user.get_username()} · {exam.name} · {timezone.localtime():%d.%m.%Y %H:%M}"
        name, suffix = base_name, 2
        while VariantTemplate.objects.filter(name=name).exists():
            name = f"{base_name} · {suffix}"
            suffix += 1
        template = VariantTemplate.objects.create(name=name, exam_version=exam, kind=VariantTemplate.Kind.CUSTOM, max_attempts=1)
        for index, s in enumerate(draft.selections, 1):
            task = catalog[s["task_id"], s["type_id"]]
            placement = resolve_placement(task, exam_version=exam, task_type_id=s["type_id"])
            VariantTask.objects.create(template=template, task=task, placement=placement, order=index)
        assignment = VariantAssignment.objects.create(user=user, template=template)
        attempt = variants.start_new_attempt(user, assignment.pk, mode=VariantAttempt.Mode.TRAINING)
        draft.selections = []
        draft.type_settings = {}
        draft.revision += 1
        draft.lifecycle_revision += 1
        draft.save()
        result = {"url": reverse("accounts:variant-attempt-solver", args=[attempt.pk]), "attempt_id": attempt.pk}
        return lifecycle.receipt(user, data.get("operation_id"), fingerprint, result)
    if action == "clear":
        draft.selections = []
        draft.type_settings = {}
    elif action == "count":
        type_id = data.get("type_id")
        if type_id is None or "count" not in data:
            raise exceptions.ValidationError("Укажите тип и количество задач.")
        minima = data.get("tag_minima", draft.type_settings.get(str(type_id), {}).get("tags", {}))
        if data["count"] == 0:
            minima = {}
        _set_count(draft, user, catalog, type_id, data["count"], minima)
    elif action == "toggle":
        task_id, type_id = data.get("task_id"), data.get("type_id")
        if task_id is None or type_id is None or "selected" not in data:
            raise exceptions.ValidationError("Укажите задачу, тип и состояние выбора.")
        old = next((s for s in draft.selections if s["task_id"] == task_id), None)
        if data["selected"]:
            task = catalog.get((task_id, type_id))
            if task is None:
                raise exceptions.ValidationError("Задача недоступна в этом типе экзамена.")
            if old and old["type_id"] != type_id:
                raise exceptions.ValidationError("Эта задача уже выбрана в другом типе.")
            if old:
                old.update(manual=True, reason="Выбрано вручную")
            else:
                if len(draft.selections) >= MAX_TASKS:
                    raise exceptions.ValidationError("В тренировке уже 100 задач.")
                draft.selections.append(_selection(task, type_id, manual=True, reason="Выбрано вручную"))
        else:
            draft.selections = [s for s in draft.selections if s["task_id"] != task_id]
        draft.type_settings[str(type_id)] = {"count": sum(s["type_id"] == type_id for s in draft.selections), "tags": {}}
    elif action == "recommend":
        # Fill to a target total; never silently replace existing choices.
        target = data.get("count", 10)
        scope_type_id = data.get("type_id")
        if scope_type_id is not None:
            if not TaskType.objects.filter(pk=scope_type_id, exam_version=exam).exists():
                raise exceptions.ValidationError("Тип не относится к этому экзамену.")
            # A type page requests a count for that type, preserving the rest of the draft.
            target = min(MAX_TASKS, target + sum(s["type_id"] != scope_type_id for s in draft.selections))
        selected_ids = {s["task_id"] for s in draft.selections}
        ranked = _ranked(user, exam, scope_type_id, exclude_solved=True)
        counts = Counter(s["type_id"] for s in draft.selections)
        # Prefer a few useful types to ten near-identical tasks; fill freely if the bank is small.
        cap = max(2, (target + 3) // 4)
        for diversify in (True, False):
            for candidate in ranked:
                if len(draft.selections) >= target:
                    break
                task = candidate.task
                placement = getattr(task, "selected_placement", None)
                type_id = placement.task_type_id if placement else task.type_id
                if scope_type_id is not None and type_id != scope_type_id:
                    continue
                if task.pk in selected_ids or (task.pk, type_id) not in catalog or (diversify and counts[type_id] >= cap):
                    continue
                draft.selections.append(_selection(task, type_id, reason=_reason(candidate)))
                selected_ids.add(task.pk)
                counts[type_id] += 1
        _sync_counts(draft)
    elif action == "mistakes":
        work = get_object_or_404(VariantAttempt, pk=data.get("attempt_id"), assignment__user=user,
                                 assignment__template__exam_version=exam)
        if not work.archived_at and not work.completed_at:
            raise exceptions.ValidationError("Сначала отправьте тренировку в архив.")
        selected_ids = {s["task_id"] for s in draft.selections}
        for row in variants.build_tasks_progress(work):
            if row["is_completed"] or row["task_id"] in selected_ids:
                continue
            type_id = (row["task_snapshot"] or {}).get("context", {}).get("task_type_id")
            task = catalog.get((row["task_id"], type_id))
            if task is not None and len(draft.selections) < MAX_TASKS:
                draft.selections.append(_selection(task, type_id, reason="Повторение после работы"))
                selected_ids.add(task.pk)
        _sync_counts(draft)
    type_order = dict(TaskType.objects.filter(exam_version=exam).values_list("pk", "display_order"))
    draft.selections.sort(key=lambda s: (type_order.get(s["type_id"], 0), s["type_id"]))
    draft.revision += 1
    draft.save()
    return draft_payload(draft)


def _work_summaries(works):
    """Fetch only answer values and latest checks, never the complete check history."""
    works = list(works)
    ids = [work.pk for work in works]
    responses = {}
    for row in VariantTaskAttempt.objects.filter(variant_attempt_id__in=ids, attempt_number=0).values(
        "variant_attempt_id", "variant_task_id", "task_snapshot__response__value",
    ):
        value = row["task_snapshot__response__value"]
        if not variants.answer_is_blank(value):
            responses.setdefault(row["variant_attempt_id"], {})[row["variant_task_id"]] = value
    latest = VariantTaskAttempt.objects.filter(
        variant_attempt_id=OuterRef("variant_attempt_id"), variant_task_id=OuterRef("variant_task_id"),
        attempt_number__gt=0,
    ).order_by("-attempt_number").values("pk")[:1]
    correct = Counter()
    modes = {work.pk: work.mode for work in works}
    for row in VariantTaskAttempt.objects.filter(variant_attempt_id__in=ids, pk=Subquery(latest), is_correct=True).values(
        "variant_attempt_id", "variant_task_id", "task_snapshot__response__value",
    ):
        wid = row["variant_attempt_id"]
        saved = responses.get(wid, {})
        if modes[wid] != "training" or (row["variant_task_id"] in saved and saved[row["variant_task_id"]] == row["task_snapshot__response__value"]):
            correct[wid] += 1
    totals = dict(VariantTask.objects.filter(template_id__in=[w.assignment.template_id for w in works]).values(
        "template_id").annotate(total=Count("id")).values_list("template_id", "total"))
    return [{"id": w.pk, "name": w.assignment.template.name, "mode": w.mode,
             "status": ("archived" if w.archived_at or w.completed_at else "active") if w.mode == "training" else ("completed" if w.completed_at else "active"),
             "total": len((w.exam_snapshot or {}).get("items", [])) or totals.get(w.assignment.template_id, 0),
             "saved": len(responses.get(w.pk, {})), "correct": correct[w.pk],
             "updated_at": w.updated_at.isoformat(), "started_at": w.started_at.isoformat(),
             "archived_at": w.archived_at.isoformat() if w.archived_at else None,
             "training_revision": w.training_revision,
             "url": reverse("accounts:variant-attempt-solver", args=[w.pk])} for w in works]


def works_payload(user, exam, *, page=1, exam_page=1):
    works = VariantAttempt.objects.filter(assignment__user=user, assignment__template__exam_version=exam).select_related(
        "assignment__template").order_by("-archived_at", "-started_at", "-pk")
    current = works.filter(mode="training", archived_at__isnull=True, completed_at__isnull=True).first()
    archives = Paginator(works.filter(mode="training", archived_at__isnull=False), 20).get_page(page)
    exams = Paginator(works.filter(mode="exam").order_by("-started_at", "-pk"), 20).get_page(exam_page)
    # Only selected exam rows need timeout reconciliation.
    exam_rows = list(exams)
    for work in exam_rows:
        variants._apply_attempt_timeout(work)
    summaries = {row["id"]: row for row in _work_summaries(([current] if current else []) + list(archives) + exam_rows)}
    draft = get_draft(user, exam)
    return {"lifecycle_revision": draft.lifecycle_revision,
            "current_training": summaries.get(current.pk) if current else None,
            "archive": {"count": archives.paginator.count, "page": archives.number, "pages": archives.paginator.num_pages,
                        "results": [summaries[w.pk] for w in archives]},
            "exams": {"count": exams.paginator.count, "page": exams.number, "pages": exams.paginator.num_pages,
                      "results": [summaries[w.pk] for w in exam_rows]}}


@transaction.atomic
def archive_work(user, attempt_id, archived, *, lifecycle_revision=None, operation_id=None):
    lifecycle.lock_user(user)
    fingerprint = lifecycle.operation_fingerprint({"attempt": attempt_id, "archived": archived, "revision": lifecycle_revision})
    previous = lifecycle.replay(user, operation_id, fingerprint)
    if previous is not None:
        return previous
    work = get_object_or_404(VariantAttempt.objects.select_for_update(of=("self",)).select_related("assignment__template"),
                             pk=attempt_id, assignment__user=user)
    if work.mode != VariantAttempt.Mode.TRAINING:
        raise exceptions.ValidationError("Пробник нельзя отправить в архив: экзаменационное время продолжает идти.")
    exam = work.assignment.template.exam_version
    draft = get_draft(user, exam)
    if lifecycle_revision is not None and lifecycle_revision != draft.lifecycle_revision:
        raise lifecycle.TrainingConflict()
    if work.completed_at:
        work.legacy_completed_at = work.legacy_completed_at or work.completed_at
        work.completed_at = None
    changed = bool(work.archived_at) != archived
    displaced_id = None
    if changed:
        now = timezone.now()
        if not archived:
            for other in lifecycle.current_training(user, exam).select_for_update().exclude(pk=work.pk).order_by("pk"):
                variants._stop_active_task_timer(other, reason="auto", now=now)
                other.archived_at = now
                other.training_revision += 1
                other.save(update_fields=["archived_at", "training_revision", "updated_at"])
                displaced_id = other.pk
        variants._stop_active_task_timer(work, reason="auto", now=now)
        work.archived_at = now if archived else None
        work.training_revision += 1
        work.save(update_fields=["archived_at", "training_revision", "completed_at", "legacy_completed_at", "updated_at"])
        draft.lifecycle_revision += 1
        draft.save(update_fields=["lifecycle_revision", "updated_at"])
    result = {"ok": True, "attempt_id": work.pk, "archived": archived,
              "lifecycle_revision": draft.lifecycle_revision, "training_revision": work.training_revision,
              "current_attempt_id": lifecycle.current_training(user, exam).values_list("pk", flat=True).first(),
              "displaced_attempt_id": displaced_id,
              "url": reverse("accounts:variant-attempt-solver", args=[work.pk])}
    return lifecycle.receipt(user, operation_id, fingerprint, result)
