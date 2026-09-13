"""Prepare, validate and publish an annual catalog without copying task content."""
from collections import defaultdict
from copy import deepcopy

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.recsys.models import (
    ExamVersion, ExamBlueprint, ExamBlueprintItem, ExamScoreScale, SkillGroup, SkillGroupItem,
    Task, TaskType, TaskPlacement, TaskTypeTransition, Attempt,
)
from .exam_context import task_filter
from .exam_history import capture_progress


@transaction.atomic
def create_next_year(source, *, year, exam_kind="ege", new_revision=False):
    source = ExamVersion.objects.select_for_update().get(pk=source.pk)
    revision = source.revision + 1 if new_revision else 1
    if new_revision:
        year, exam_kind = source.year, source.exam_kind
    if not year or not 2000 <= int(year) <= 2200 or (not new_revision and source.year and int(year) <= source.year):
        raise ValidationError("Укажите следующий экзаменационный год.")
    existing = ExamVersion.objects.filter(subject=source.subject, exam_kind=exam_kind, year=year, revision=revision).first()
    if existing:
        if existing.copied_from_id != source.pk:
            raise ValidationError("Версия этого года уже существует и создана из другого источника.")
        return existing
    label = f"{dict(ege='ЕГЭ', oge='ОГЭ').get(exam_kind, exam_kind.upper())} {year}"
    slug = f"{source.subject.slug or source.subject_id}-{exam_kind}-{year}"
    target = ExamVersion.objects.create(
        subject=source.subject, name=label + (f" (ред. {revision})" if revision > 1 else ""), slug=slug + (f"-r{revision}" if revision > 1 else ""),
        exam_kind=exam_kind, year=year, revision=revision, copied_from=source, start_info=source.start_info,
    )
    type_map = {}
    for old in source.task_types.prefetch_related("required_tags"):
        new = TaskType.objects.create(subject=source.subject, exam_version=target, name=old.name, slug=old.slug,
                                      description=old.description, display_order=old.display_order,
                                      answer_schema=old.answer_schema, scoring_scheme=old.scoring_scheme, max_score=old.max_score)
        new.required_tags.set(old.required_tags.all())
        type_map[old.pk] = new
        TaskTypeTransition.objects.create(target_exam=target, source_type=old, target_type=new)
        source_tasks = Task.objects.filter(task_filter(task_type_ids=[old.pk])).distinct()
        for task in source_tasks:
            if not task.placements.exists() and task.type.exam_version_id:
                TaskPlacement.objects.get_or_create(task=task, task_type=old)
            previous = task.placements.filter(task_type=old).first()
            TaskPlacement.objects.create(task=task, task_type=new, status=TaskPlacement.Status.DRAFT,
                                         scoring_scheme=previous.scoring_scheme if previous else "",
                                         max_score=previous.max_score if previous else None,
                                         answer_schema=previous.answer_schema if previous else None)
    old_blueprint = ExamBlueprint.objects.filter(exam_version=source).first()
    if old_blueprint:
        blueprint = ExamBlueprint.objects.create(exam_version=target, subject=target.subject, title=old_blueprint.title,
                                                time_limit=old_blueprint.time_limit, max_attempts=old_blueprint.max_attempts, is_active=True)
        for item in old_blueprint.items.all():
            ExamBlueprintItem.objects.create(blueprint=blueprint, task_type=type_map[item.task_type_id],
                                             count=item.count, order=item.order, section=item.section, score_override=item.score_override)
    old_scale = ExamScoreScale.objects.filter(exam_version=source).first()
    if old_scale:
        ExamScoreScale.objects.create(exam_version=target, max_primary=old_scale.max_primary, mapping=deepcopy(old_scale.mapping), is_active=False)
    for old_group in source.skill_groups.all():
        group = SkillGroup.objects.create(exam_version=target, title=old_group.title)
        for item in old_group.items.all():
            SkillGroupItem.objects.create(group=group, skill=item.skill, label=item.label, order=item.order)
    return target


def placement_plan(exam):
    source_ids = set(TaskPlacement.objects.filter(task_type__exam_version=exam.copied_from).values_list("task_id", flat=True)) if exam.copied_from_id else set()
    result = defaultdict(set)
    errors = []
    for row in exam.type_transitions.select_related("source_type", "target_type"):
        try:
            if not exam.published_at:
                row.clean()
        except ValidationError as exc:
            errors.extend(exc.messages)
            continue
        if not row.approved:
            errors.append(f"Соответствие #{row.pk} не проверено.")
        if not row.target_type_id:
            continue
        if row.relation == TaskTypeTransition.Relation.ADDED:
            continue
        eligible = set(Task.objects.filter(task_filter(task_type_ids=[row.source_type_id])).values_list("pk", flat=True))
        if row.relation == TaskTypeTransition.Relation.EQUIVALENT:
            if set(row.source_type.required_tags.values_list("pk", flat=True)) != set(row.target_type.required_tags.values_list("pk", flat=True)):
                errors.append(f"{row.target_type.name}: требования различаются; укажите частичное соответствие.")
            result[row.target_type_id].update(eligible)
        else:
            selected = set(row.task_ids)
            if not selected or not selected.issubset(eligible):
                errors.append(f"Соответствие #{row.pk}: нужен непустой список задач исходного типа.")
            result[row.target_type_id].update(selected & eligible)
    for placement in TaskPlacement.objects.filter(task_type__exam_version=exam).exclude(status=TaskPlacement.Status.RETIRED):
        if placement.task_id not in source_ids:
            result[placement.task_type_id].add(placement.task_id)
    return result, errors


def match_blueprint(pools):
    """Bipartite matching: overlapping pools must still fill every slot uniquely."""
    assigned = {}
    slots = []
    for type_id, count, candidates in pools:
        slots.extend([(type_id, list(candidates)) for _ in range(count)])

    def visit(index, seen):
        for task_id in slots[index][1]:
            if task_id in seen:
                continue
            seen.add(task_id)
            if task_id not in assigned or visit(assigned[task_id], seen):
                assigned[task_id] = index
                return True
        return False

    for index in range(len(slots)):
        if not visit(index, set()):
            raise ValidationError("Нельзя заполнить все позиции различными задачами: проверьте пересечение пулов.")
    return [(slots[index][0], task_id) for task_id, index in sorted(assigned.items(), key=lambda pair: pair[1])]


def validate_rollover(exam):
    plan, errors = placement_plan(exam)
    if not exam.year or not exam.exam_kind:
        errors.append("Заполните вид экзамена и год.")
    if not exam.publication_info.get("requirements_checked") or not exam.publication_info.get("source_document") or not exam.publication_info.get("scale_checked"):
        errors.append("Нужны проверка требований и ссылка/редакция документа-основания.")
    incoming = set(exam.type_transitions.exclude(target_type=None).values_list("target_type_id", flat=True))
    for task_type in exam.task_types.prefetch_related("required_tags"):
        try:
            task_type.full_clean()
            if task_type.max_score < 1:
                raise ValidationError(f"{task_type.name}: максимум должен быть положительным.")
            if task_type.answer_schema:
                task_type.answer_schema.full_clean()
        except ValidationError as exc:
            errors.extend(exc.messages)
        if task_type.pk not in incoming:
            errors.append(f"{task_type.name}: отсутствует строка соответствия/нового типа.")
        if not task_type.required_tags.exists():
            errors.append(f"{task_type.name}: укажите учебные темы в требованиях типа.")
        bank = Task.objects.filter(pk__in=plan[task_type.pk], status=Task.Status.PUBLISHED)
        for tag in task_type.required_tags.all():
            if not bank.filter(tags=tag).exists():
                errors.append(f"{task_type.name}: нет опубликованных задач для темы {tag.name}.")
    if exam.copied_from_id:
        covered = set(exam.type_transitions.values_list("source_type_id", flat=True))
        for old in exam.copied_from.task_types.exclude(pk__in=[pk for pk in covered if pk]):
            errors.append(f"{old.name}: не указано соответствие или исключение.")
    blueprint = ExamBlueprint.objects.filter(exam_version=exam, is_active=True).first()
    if not blueprint or not blueprint.items.exists():
        errors.append("Заполните структуру экзамена.")
    else:
        pools = []
        primary_max = 0
        for item in blueprint.items.select_related("task_type"):
            try:
                item.full_clean()
                if item.count < 1 or item.score_override == 0:
                    raise ValidationError("Количество задач и максимальный балл должны быть положительными.")
            except ValidationError as exc:
                errors.extend(exc.messages)
            primary_max += item.count * (item.score_override or item.task_type.max_score)
            ids = list(Task.objects.filter(pk__in=plan[item.task_type_id], status=Task.Status.PUBLISHED).values_list("pk", flat=True))
            pools.append((item.task_type_id, item.count, ids))
        try:
            match_blueprint(pools)
        except ValidationError as exc:
            errors.extend(exc.messages)
        scale = ExamScoreScale.objects.filter(exam_version=exam, is_active=True).first()
        if scale:
            try:
                scale.full_clean()
                if scale.max_primary != primary_max:
                    raise ValidationError("Максимум шкалы не совпадает с суммой баллов структуры экзамена.")
            except ValidationError as exc:
                errors.extend(exc.messages)
    return {"errors": errors, "types": {key: sorted(value) for key, value in plan.items()}, "ready": not errors,
            "type_rows": [{"id": row.pk, "name": row.name, "count": len(plan[row.pk]),
                           "requirements": list(row.required_tags.values_list("name", flat=True))} for row in exam.task_types.all()]}


@transaction.atomic
def publish_exam(exam, *, make_default=False):
    # Serialize the default pointer across different annual versions of a subject.
    type(exam.subject).objects.select_for_update().get(pk=exam.subject_id)
    exam = ExamVersion.objects.select_for_update().get(pk=exam.pk)
    if exam.published_at:
        return exam
    report = validate_rollover(exam)
    if report["errors"]:
        raise ValidationError(report["errors"])
    for type_id, task_ids in report["types"].items():
        TaskPlacement.objects.filter(task_type_id=type_id).exclude(task_id__in=task_ids).update(status=TaskPlacement.Status.RETIRED)
        for task_id in task_ids:
            TaskPlacement.objects.update_or_create(task_id=task_id, task_type_id=type_id, defaults={"status": TaskPlacement.Status.ACTIVE})
    if make_default:
        ExamVersion.objects.filter(subject=exam.subject, exam_kind=exam.exam_kind, is_default=True).update(is_default=False)
        exam.is_default = True
    exam.status = ExamVersion.Status.ACTIVE
    exam.published_at = timezone.now()
    exam._annual_lifecycle = True
    exam.save()
    del exam._annual_lifecycle
    return exam


@transaction.atomic
def archive_exam(exam):
    from django.contrib.auth import get_user_model
    exam = ExamVersion.objects.select_for_update().get(pk=exam.pk)
    if exam.status == ExamVersion.Status.ARCHIVED:
        return exam
    now = timezone.now()
    user_ids = set(Attempt.objects.filter(exam_version=exam).values_list("user_id", flat=True))
    user_ids.update(exam.students_preparing.values_list("user_id", flat=True))
    for user in get_user_model().objects.filter(pk__in=user_ids):
        capture_progress(user, exam, as_of=now)
    exam.status = ExamVersion.Status.ARCHIVED
    exam.is_default = False
    exam._annual_lifecycle = True
    exam.save(update_fields=["status", "is_default", "updated_at"])
    del exam._annual_lifecycle
    return exam
