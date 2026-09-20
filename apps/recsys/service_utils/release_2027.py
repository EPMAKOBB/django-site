"""Prepare the reviewed informatics catalog using stable slugs, never local IDs.

This prepares a draft only. Publication remains the normal reviewed lifecycle
action. The current database is chosen by Django settings, not by this module.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction

from apps.recsys.models import AnswerSchema, ExamVersion, Source, Task, TaskAttachment, TaskPlacement, TaskTag
from .exam_rollover import validate_rollover

RELEASE = "informatics-ege-2027-release-v1"
DATA = Path(__file__).resolve().parents[3] / "scripts" / "data"


def content_spec():
    first = json.loads((DATA / "inf_ege_2027_demo13.json").read_text(encoding="utf-8"))
    first.update(number=13, tags=[first["tag"]])
    recursion = json.loads((DATA / "inf_ege_2027_recursion.json").read_text(encoding="utf-8"))
    rest = json.loads((DATA / "inf_ege_2027_completion.json").read_text(encoding="utf-8"))
    items = [first, recursion] + [row for row in rest if not row.get("excluded")]
    for row in items:
        row.setdefault("slug", f"inf-ege-2027-demo-{row['number']}")
        row.setdefault("title", f"Демоверсия ЕГЭ 2027. Задание {row['number']}")
        row.setdefault("tags", [row["tag"]] if "tag" in row else [])
        row.setdefault("source_name", first["source_name"])
        row.setdefault("source_slug", first["source_slug"])
        row.setdefault("source_description", first["source_description"])
    return items


def _review(exam):
    # Evaluate content without setting the human-review checkboxes in the DB.
    original = deepcopy(exam.publication_info)
    exam.publication_info.update(requirements_checked=True, scale_checked=True)
    report = validate_rollover(exam)
    exam.publication_info = original
    return {"exam_slug": exam.slug, "exam_id": exam.pk, "status": exam.status,
            "ready_for_review": report["ready"], "errors": report["errors"],
            "types": report["type_rows"], "publication_performed": False}


def prepare_release(source, *, files_dir, apply=False):
    from scripts.prepare_informatics_2027 import prepare_transition

    items = content_spec()
    expected_hashes = json.loads((DATA / "inf_ege_2027_file_hashes.json").read_text(encoding="utf-8"))
    fingerprint = hashlib.sha256(json.dumps({"release": RELEASE, "tasks": items, "files": expected_hashes}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    contents = {}
    for name, expected in expected_hashes.items():
        path = Path(files_dir) / name
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValidationError(f"Файл {name} не совпадает с проверенной демоверсией.")
        contents[name] = content
    written = []
    try:
        with transaction.atomic():
            # Serialize preparations for the same subject, including absent target.
            type(source.subject).objects.select_for_update().get(pk=source.subject_id)
            source = ExamVersion.objects.select_for_update().get(pk=source.pk)
            if source.subject.slug != "inf" or source.status != "active":
                raise ValidationError("Нужен активный исходный экзамен предмета inf.")
            if source.year not in (None, 2026) or "2026" not in source.name:
                raise ValidationError("Исходный экзамен должен относиться к 2026 году.")
            old = ExamVersion.objects.filter(subject=source.subject, year=2027, exam_kind="ege", revision=1).first()
            if old:
                if old.copied_from_id != source.pk or old.publication_info.get("release_fingerprint") != fingerprint:
                    raise ValidationError("Сезон 2027 уже существует и не принадлежит этому выпуску. Автоматическая перезапись запрещена.")
                # A repeated import must not reactivate retired tasks or overwrite
                # the editor's changes. Re-evaluate and return without mutations.
                result = _review(old)
                result.update(applied=apply, already_prepared=True)
                return result
            exam = prepare_transition(source, source_document="Проект ФИПИ 21.08.2026; проверка 20.09.2026. Уточнение центра кластера согласовано пользователем.")
            single = AnswerSchema.objects.get(name="single_uint")
            pair = AnswerSchema.objects.get(name="double_uint")
            if single.config.get("rows") != 1 or single.config.get("cols") != 1 or single.config.get("input_type") != "uint":
                raise ValidationError("Схема single_uint отличается от проверенной.")
            if pair.config.get("rows") != 1 or pair.config.get("cols") != 2 or pair.config.get("input_type") != "uint":
                raise ValidationError("Схема double_uint отличается от проверенной.")
            graph = exam.task_types.get(slug="23")
            graph.description = "Длина пути в ориентированном графе. Кратчайший путь в ациклическом взвешенном графе."
            graph.answer_schema = single
            graph.save()
            graph_tag, _ = TaskTag.objects.get_or_create(subject=exam.subject, name="Кратчайший путь в ориентированном графе", defaults={"slug": "directed-graph-shortest-path"})
            graph.required_tags.add(graph_tag)
            for number in (26, 27):
                typ = exam.task_types.get(slug=str(number))
                typ.scoring_scheme, typ.answer_schema = "ege_pairs_2027", pair
                typ.save()
                # These are new, unissued draft placements, not old-year rules.
                TaskPlacement.objects.filter(task_type=typ).update(scoring_scheme="ege_pairs_2027", answer_schema=pair)
            clustering = exam.task_types.get(slug="27")
            clustering.required_tags.remove(*clustering.required_tags.filter(name="Аномалии"))
            row = exam.type_transitions.get(target_type=clustering)
            row.relation, row.task_ids, row.allow_empty_source_pool = "partial", [], True
            row.notes = "Старые задачи с четырьмя числами остаются в 2026. Новый банк 2027 наполняется новыми задачами. Аномалии сохранены как дополнительная тема, не обязательная для текущего начального банка."
            row.save()
            # Empty transfer must not leave the cloned old tasks as draft extras.
            TaskPlacement.objects.filter(task_type=clustering).update(status="retired")
            imported = []
            for item in items:
                typ = exam.task_types.get(slug=str(item["number"]))
                task = Task.objects.filter(slug=item["slug"]).first()
                if task:
                    if task.subject_id != exam.subject_id or task.exam_version_id not in {source.pk, exam.pk}:
                        raise ValidationError(f"Задача {task.slug} принадлежит другому экзамену.")
                    if task.type.slug != typ.slug or any(getattr(task, field) != item[field] for field in ("description", "correct_answer")):
                        raise ValidationError(f"Задача {task.slug} отличается от проверенного содержания.")
                    expected_tags = set(item["tags"])
                    if not expected_tags.issubset(task.tags.values_list("name", flat=True)) or task.status != "published":
                        raise ValidationError(f"Существующая задача {task.slug} требует проверки тегов/публикации; она не изменена.")
                    if task.exam_version_id == source.pk:
                        if not task.placements.filter(task_type=task.type, status="active").exists():
                            raise ValidationError(f"Для {task.slug} сначала восстановите исходные назначения.")
                else:
                    task_source, _ = Source.objects.get_or_create(name=item["source_name"], defaults={
                        "slug": item["source_slug"], "exam_version": exam, "description": item["source_description"],
                    })
                    task = Task.objects.create(subject=exam.subject, exam_version=exam, type=typ, source=task_source,
                        slug=item["slug"], title=item["title"], description=item["description"], correct_answer=item["correct_answer"],
                        rendering_strategy=item.get("rendering_strategy", "markdown"), status="published",
                        scoring_scheme="ege_pairs_2027" if item["number"] == 27 else "binary", max_score=2 if item["number"] == 27 else 1)
                    for name in item["tags"]:
                        tag, _ = TaskTag.objects.get_or_create(subject=exam.subject, name=name)
                        task.tags.add(tag)
                TaskPlacement.objects.get_or_create(task=task, task_type=typ, defaults={"status": "draft"})
                if item.get("file"):
                    name = item["file"]
                    attachment = task.attachments.filter(download_name_override=name).first()
                    if attachment:
                        with attachment.file.open("rb") as stream:
                            if hashlib.sha256(stream.read()).hexdigest() != expected_hashes[name]:
                                raise ValidationError(f"Вложение задачи {task.slug} отличается от проверенного.")
                    elif apply:
                        attachment = TaskAttachment(task=task, kind="file", download_name_override=name)
                        attachment.file.save(name, ContentFile(contents[name]), save=False)
                        written.append((attachment.file.storage, attachment.file.name))
                        attachment.save()
                imported.append({"slug": task.slug, "task_id": task.pk, "type": typ.slug})
            info = exam.publication_info
            info.update(release=RELEASE, release_fingerprint=fingerprint, scale_checked=True,
                        requirements_checked=False, pending_review=["Подтверждение требований перед публикацией"],
                        optional_topics={"27": ["Аномалии"]},
                        limitations=["Проект ФИПИ", "Тип 23: начальный банк кратчайшего пути", "Шкала перевода отключена"])
            exam.save()
            result = _review(exam)
            result.update(applied=apply, already_prepared=False, tasks=imported, fingerprint=fingerprint)
            if not apply:
                transaction.set_rollback(True)
        return result
    except Exception:
        for storage, name in written:
            storage.delete(name)
        raise
