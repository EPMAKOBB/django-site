"""Server-owned identity of an issued task, independent of annual catalog changes."""
from copy import deepcopy
from secrets import randbits

from django.core.exceptions import ValidationError
from django.db.models import Q

from apps.recsys.models import Task, TaskPlacement


def task_filter(*, exam_version=None, task_type_ids=None, for_issuance=False):
    """Explicit placements take precedence; unconverted legacy tasks remain usable."""
    current = Q(placements__status=TaskPlacement.Status.ACTIVE)
    legacy = Q(placements__isnull=True)
    if exam_version is not None:
        current &= Q(placements__task_type__exam_version=exam_version)
        legacy &= Q(exam_version=exam_version)
    if task_type_ids:
        current &= Q(placements__task_type_id__in=task_type_ids)
        legacy &= Q(type_id__in=task_type_ids)
    if for_issuance:
        current &= ~Q(placements__task_type__exam_version__status="archived")
        current &= ~Q(placements__task_type__exam_version__status="draft", placements__task_type__exam_version__copied_from__isnull=False)
        legacy &= ~Q(exam_version__status="archived")
        legacy &= ~Q(exam_version__status="draft", exam_version__copied_from__isnull=False)
    return current | legacy


def ensure_exam_available(exam):
    if exam and (exam.status == "archived" or (exam.copied_from_id and exam.status != "active")):
        raise ValidationError("Эта версия экзамена недоступна для новой выдачи.")


def resolve_placement(task, *, exam_version=None, task_type_id=None, placement=None, allow_retired=False):
    if placement is not None:
        if placement.task_id != task.pk:
            raise ValidationError("Назначение относится к другой задаче.")
        if exam_version is not None and placement.task_type.exam_version_id != exam_version.pk:
            raise ValidationError("Назначение относится к другому экзамену.")
        if task_type_id is not None and placement.task_type_id != task_type_id:
            raise ValidationError("Назначение относится к другому типу.")
        if not allow_retired and placement.status != TaskPlacement.Status.ACTIVE:
            raise ValidationError("Назначение недоступно для новой выдачи.")
        if not allow_retired:
            ensure_exam_available(placement.task_type.exam_version)
        return placement
    rows = task.placements.select_related("task_type__exam_version", "answer_schema", "task_type__answer_schema")
    if exam_version is not None:
        rows = rows.filter(task_type__exam_version=exam_version)
    if task_type_id is not None:
        rows = rows.filter(task_type_id=task_type_id)
    if not allow_retired:
        rows = rows.filter(status=TaskPlacement.Status.ACTIVE)
    options = list(rows[:2])
    if len(options) > 1:
        raise ValidationError("Укажите назначение задачи: подходят несколько типов или лет.")
    if options:
        if not allow_retired:
            ensure_exam_available(options[0].task_type.exam_version)
        return options[0]
    if task.placements.exists():
        raise ValidationError("Задача не включена в выбранный экзамен/тип.")
    # Compatibility until backfill. Never infer another annual type by its number.
    legacy_exam_id = task.type.exam_version_id or task.exam_version_id
    if exam_version is not None and legacy_exam_id != exam_version.pk:
        raise ValidationError("Задача не относится к выбранному экзамену.")
    if task_type_id is not None and task.type_id != task_type_id:
        raise ValidationError("Задача не относится к выбранному типу.")
    if task.type.exam_version_id and task.exam_version_id not in (None, task.type.exam_version_id):
        raise ValidationError("Противоречивые версии задачи и типа требуют проверки.")
    if task.type.exam_version_id:
        if not allow_retired:
            ensure_exam_available(task.type.exam_version)
        return TaskPlacement.objects.get_or_create(task=task, task_type=task.type)[0]
    return None


def grading_context(task, placement=None):
    task_type = placement.task_type if placement else task.type
    schema = (placement.answer_schema if placement else None) or task.answer_schema or task_type.answer_schema
    return {
        "scoring_scheme": (placement.scoring_scheme if placement else None) or task.scoring_scheme or task_type.scoring_scheme,
        "max_score": int((placement.max_score if placement else None) or task.max_score or task_type.max_score or 1),
        "answer_schema": {"id": schema.pk, "name": schema.name, "config": deepcopy(schema.config)} if schema else None,
    }


def identity_context(task, placement=None, *, exam_version=None, order=None):
    task_type = placement.task_type if placement else task.type
    exam = exam_version or task_type.exam_version or task.exam_version
    return {
        "version": 1,
        "task_id": task.pk,
        "placement_id": placement.pk if placement else None,
        "exam_version_id": exam.pk if exam else None,
        "exam_name": exam.name if exam else "",
        "task_type_id": task_type.pk,
        "task_type_name": task_type.name,
        "display_order": task_type.display_order,
        "order": order,
        "tag_ids": list(task.tags.values_list("pk", flat=True)),
        "skill_ids": list(task.skills.values_list("pk", flat=True)),
        "level_band": task.level_band,
        "expected_time_seconds": task.expected_time_seconds,
    }


def snapshot_task(task, placement=None, *, exam_version=None, order=None, seed=None):
    from apps.recsys.presentation.tasks import build_task_statement_payload, statement_fingerprint
    from . import task_generation
    context = identity_context(task, placement, exam_version=exam_version, order=order)
    snapshot = {
        "task_id": task.pk, "type": "dynamic" if task.is_dynamic else "static",
        "title": task.title, "description": task.description,
        "rendering_strategy": task.rendering_strategy,
        "correct_answer": deepcopy(task.correct_answer),
        "context": context, "task_type_name": context["task_type_name"],
        **grading_context(task, placement),
        "storage_files": list(task.attachments.exclude(file="").values_list("file", flat=True)) + ([task.image.name] if task.image else []),
    }
    if task.is_dynamic:
        seed = seed if seed is not None else randbits(53)
        snapshot.update(seed=seed, generation_mode=task.dynamic_mode, generator_slug=task.generator_slug)
        if task.dynamic_mode == Task.DynamicMode.PRE_GENERATED:
            dataset = task.pick_pregenerated_dataset(seed=seed)
            if dataset is None:
                raise ValidationError("Нет предгенерированных данных для задачи.")
            snapshot.update(dataset_id=dataset.pk, payload=deepcopy(dataset.parameter_values),
                            correct_answer=deepcopy(dataset.correct_answer),
                            content={"title": task.title, "statement": task.render_template_payload(dataset.parameter_values)})
        else:
            result = task_generation.generate(task, deepcopy(task.default_payload), seed=seed)
            snapshot.update(payload=dict(result.payload or task.default_payload), content=dict(result.content))
            if result.answers is not None:
                snapshot["answers"] = deepcopy(result.answers)
                snapshot["correct_answer"] = deepcopy(result.answers)
            if result.meta is not None:
                snapshot["meta"] = dict(result.meta)
    if task.is_dynamic:
        content = snapshot.get("content", {})
        snapshot["description"] = str(content.get("statement") or content.get("question") or snapshot["description"])
    statement = build_task_statement_payload(task=task, statement_source=snapshot)
    snapshot.update(task_body_html=statement["task_body_html"], image=statement["image"], attachments=statement["attachments"], statement_fingerprint=statement_fingerprint(snapshot))
    return snapshot


def prepare_attempt_context(attempt):
    if attempt.variant_task_attempt_id and not attempt.task_snapshot:
        source = attempt.variant_task_attempt.task_snapshot or {}
        attempt.task_snapshot = deepcopy(source.get("task", source))
        attempt.response_snapshot = deepcopy(source.get("response", {}))
    context = attempt.context_snapshot or (attempt.task_snapshot or {}).get("context")
    if context:
        if context.get("task_id") != attempt.task_id:
            raise ValidationError("Снимок относится к другой задаче.")
        attempt.context_snapshot = deepcopy(context)
        attempt.exam_version_id = context.get("exam_version_id")
        attempt.task_type_id = context.get("task_type_id")
        attempt.placement_id = context.get("placement_id")
        attempt.context_origin = context.get("origin", "issued")
        return
    exam = attempt.exam_version
    if attempt.variant_task_attempt_id:
        exam = attempt.variant_task_attempt.variant_attempt.assignment.template.exam_version
    placement = resolve_placement(attempt.task, exam_version=exam, task_type_id=attempt.task_type_id, placement=attempt.placement)
    attempt.context_snapshot = identity_context(attempt.task, placement, exam_version=exam)
    attempt.placement = placement
    attempt.task_type_id = attempt.context_snapshot["task_type_id"]
    attempt.exam_version_id = attempt.context_snapshot["exam_version_id"]
    attempt.context_origin = "recorded"
    if not attempt.task_snapshot:
        # Direct legacy API records a result, not a previously issued randomized question.
        attempt.task_snapshot = {"context": deepcopy(attempt.context_snapshot), "task_id": attempt.task_id,
                                 "title": attempt.task.title, "description": attempt.task.description,
                                 **grading_context(attempt.task, placement)}


def bind_task(task, placement):
    """Read-only presentation copy; never save a task returned by this function."""
    from copy import copy
    result = copy(task)
    result._state = deepcopy(task._state)
    result.selected_placement = placement
    if placement:
        result.type = placement.task_type
        result.exam_version = placement.task_type.exam_version
    return result


def display_tasks(queryset, *, exam_ids=None, task_type_id=None):
    for task in queryset.prefetch_related("placements__task_type__exam_version"):
        placements = [p for p in task.placements.all() if p.status == TaskPlacement.Status.ACTIVE
                      and (not exam_ids or p.task_type.exam_version_id in exam_ids)
                      and (not task_type_id or p.task_type_id == task_type_id)]
        shown = bind_task(task, placements[0]) if len(placements) == 1 else task
        shown.display_placements = placements
        yield shown


def public_snapshot(snapshot, *, reveal=False):
    result = deepcopy(snapshot or {})
    if not reveal:
        result.pop("correct_answer", None)
        result.pop("answers", None)
    result.pop("storage_files", None)
    return result
