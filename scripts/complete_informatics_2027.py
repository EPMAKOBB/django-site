"""Complete verified content in the LOCAL sandbox; publication is a separate step.

Default: roll back all database changes. --apply persists content. No production
settings or credentials are accepted. Demo attachments stay in local media.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=Path, required=True)
    parser.add_argument("--files-2026", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    os.environ["DJANGO_SETTINGS_MODULE"] = "fractalschool.exam_sandbox_settings"
    import django
    django.setup()
    from django.conf import settings
    from django.core.files.base import ContentFile
    from django.db import transaction
    from apps.recsys.models import AnswerSchema, ExamVersion, Source, Task, TaskAttachment, TaskPlacement, TaskTag
    from apps.recsys.service_utils.exam_rollover import validate_rollover
    from scripts.prepare_informatics_2027 import retained_data_fingerprint
    from scripts.verify_informatics_2027_content import verify_content, verify_adapted_2026_cluster

    db = settings.DATABASES["default"]
    if (db["HOST"], str(db["PORT"]), db["NAME"]) != ("127.0.0.1", "55438", "exam_year_sandbox"):
        raise RuntimeError("Разрешена только локальная exam_year_sandbox:55438.")
    verification = verify_content(args.files)
    verification["adapted27"] = verify_adapted_2026_cluster(args.files_2026 / "DEMO_27_B.txt")
    data = json.loads((ROOT / "scripts/data/inf_ege_2027_completion.json").read_text(encoding="utf-8"))
    created_files = []
    try:
        with transaction.atomic():
            exam = ExamVersion.objects.select_for_update().get(slug="inf-ege-2027")
            if exam.published_at or exam.status != "draft":
                raise RuntimeError("Нужен неопубликованный черновик 2027.")
            before = retained_data_fingerprint(exam.copied_from)
            recursion = Task.objects.select_for_update().get(pk=1177)
            if recursion.title != "k27076" or recursion.correct_answer != verification["recursion_1177"]:
                raise RuntimeError("Задача по рекурсии изменилась; нужна повторная проверка.")
            if recursion.status not in {"draft", "published"}:
                raise RuntimeError("Неожиданный статус задачи по рекурсии.")
            if recursion.status != "published":
                recursion.status = "published"
                recursion.save(update_fields=["status", "updated_at"])
            source = Source.objects.get(name="ДЕМО 2027 Инф", exam_version=exam)
            # The 2027 rubric is separate so old work keeps its frozen rules.
            pair_schema = AnswerSchema.objects.get(name="double_uint")
            for number in (26, 27):
                pair_type = exam.task_types.get(slug=str(number))
                pair_type.scoring_scheme = "ege_pairs_2027"
                pair_type.answer_schema = pair_schema
                pair_type.save()
                TaskPlacement.objects.filter(task_type=pair_type).update(scoring_scheme="ege_pairs_2027", answer_schema=pair_schema)
            row27 = exam.type_transitions.get(target_type__slug="27")
            row27.relation = "partial"
            row27.task_ids = []
            row27.allow_empty_source_pool = True
            row27.notes = "Все десять старых задач требуют четыре числа. Исходные задачи сохранены в 2026; для 2027 используются отдельные задачи с одной парой чисел."
            row27.save()
            created_tasks = []
            task_ids = []
            for item in data:
                if item.get("excluded"):
                    continue
                number = item["number"]
                typ = exam.task_types.get(slug=str(number))
                tag, _ = TaskTag.objects.get_or_create(subject=exam.subject, name=item["tag"], defaults={"slug": item["tag_slug"]})
                typ.required_tags.add(tag)
                if number == 23:
                    typ.description = "Длина пути в ориентированном графе. Кратчайший путь в ациклическом взвешенном графе."
                    typ.answer_schema = AnswerSchema.objects.get(name="single_uint")
                    typ.save()
                    row = exam.type_transitions.get(target_type=typ)
                    row.notes = "Новый тип. Начальный банк: кратчайший путь, демоверсия 2027; другие разновидности пока не представлены."
                    row.save()
                task_source = source
                if item.get("source_name"):
                    task_source, _ = Source.objects.get_or_create(name=item["source_name"], defaults={
                        "slug": item.get("source_slug", "demo2026-b-adapted-2027"), "exam_version": exam,
                        "description": item.get("source_description", "Часть B задания 27 демоверсии 2026 выделена в самостоятельную учебную задачу с двумя числами в ответе."),
                    })
                task, created = Task.objects.get_or_create(slug=item.get("slug", f"inf-ege-2027-demo-{number}"), defaults={
                    "subject": exam.subject, "exam_version": exam, "type": typ, "source": task_source,
                    "title": item.get("title", f"Демоверсия ЕГЭ 2027. Задание {number}"), "description": item["description"],
                    "correct_answer": item["correct_answer"], "status": "published", "rendering_strategy": "markdown",
                    "max_score": 2 if number == 27 else 1, "scoring_scheme": "ege_pairs_2027" if number == 27 else "binary",
                })
                if (task.description, task.correct_answer, task.type_id, task.source_id) != (item["description"], item["correct_answer"], typ.pk, task_source.pk):
                    raise RuntimeError(f"Задача {task.slug} уже существует с другим содержимым.")
                if created:
                    created_tasks.append(task.pk)
                task_ids.append(task.pk)
                task.tags.add(tag)
                if item.get("extra_tag"):
                    task.tags.add(typ.required_tags.get(name=item["extra_tag"]))
                TaskPlacement.objects.get_or_create(task=task, task_type=typ, defaults={"status": "draft"})
                file_root = args.files_2026 if item.get("file_year") == 2026 else args.files
                content = (file_root / item["file"]).read_bytes()
                existing = task.attachments.filter(download_name_override=item["file"]).first()
                if existing:
                    with existing.file.open("rb") as stream:
                        if hashlib.sha256(stream.read()).digest() != hashlib.sha256(content).digest():
                            raise RuntimeError(f"Вложение {item['file']} не совпадает с исходным файлом.")
                elif args.apply:
                    attachment = TaskAttachment(task=task, kind="file", download_name_override=item["file"])
                    attachment.file.save(item["file"], ContentFile(content), save=False)
                    created_files.append((attachment.file.storage, attachment.file.name))
                    attachment.save()
            after = retained_data_fingerprint(exam.copied_from)
            for key in before.keys() - {"tasks", "task_tags"}:
                if before[key] != after[key]:
                    raise RuntimeError(f"Изменились исторические данные: {key}.")
            report = {"applied": args.apply, "recursion_task_id": recursion.pk, "demo_task_ids": task_ids,
                      "created_task_ids": created_tasks, "verification": verification,
                      "history_and_mastery_unchanged": True, "validation": validate_rollover(exam)}
            if not args.apply:
                transaction.set_rollback(True)
    except Exception:
        for storage, name in created_files:
            storage.delete(name)
        raise
    report_path = ROOT / ".local/exam-sandbox/transition-2027/content-completion.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "validation"}, ensure_ascii=False, indent=2))
    print(json.dumps(report["validation"]["errors"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
