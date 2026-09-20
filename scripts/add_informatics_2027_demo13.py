"""Add the verified demo task to the existing local sandbox draft, once."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.path.insert(0, str(ROOT))
    os.environ["DJANGO_SETTINGS_MODULE"] = "fractalschool.exam_sandbox_settings"
    import django
    django.setup()
    from django.conf import settings
    from django.db import transaction
    from apps.recsys.models import ExamVersion, Source, Task, TaskPlacement
    from apps.recsys.service_utils.exam_rollover import validate_rollover
    from apps.recsys.service_utils.grading import grade_answer
    from apps.recsys.forms import TaskAnswerForm
    from scripts.prepare_informatics_2027 import retained_data_fingerprint

    db = settings.DATABASES["default"]
    if (db["HOST"], str(db["PORT"]), db["NAME"]) != ("127.0.0.1", "55438", "exam_year_sandbox"):
        raise RuntimeError("Разрешена только локальная exam_year_sandbox на порту 55438.")
    data = json.loads((ROOT / "scripts/data/inf_ege_2027_demo13.json").read_text(encoding="utf-8"))
    with transaction.atomic():
        exam = ExamVersion.objects.select_for_update().get(slug="inf-ege-2027")
        if exam.status != "draft" or exam.published_at:
            raise RuntimeError("Ожидается неопубликованный черновик ЕГЭ 2027.")
        typ = exam.task_types.get(slug="13")
        tag = typ.required_tags.get(name=data["tag"])
        before = retained_data_fingerprint(exam.copied_from)
        source, _ = Source.objects.get_or_create(name=data["source_name"], defaults={
            "slug": data["source_slug"], "exam_version": exam, "description": data["source_description"],
        })
        if source.exam_version_id != exam.pk:
            raise RuntimeError("Источник с таким именем уже относится к другому экзамену.")
        task, created = Task.objects.get_or_create(slug=data["slug"], defaults={
            "subject": exam.subject, "exam_version": exam, "type": typ, "source": source,
            "title": data["title"], "description": data["description"], "correct_answer": data["correct_answer"],
            "status": "published", "rendering_strategy": "markdown", "is_dynamic": False,
            "scoring_scheme": "binary", "max_score": 1,
        })
        if (task.type_id, task.exam_version_id, task.correct_answer, task.description, task.source_id) != (typ.pk, exam.pk, data["correct_answer"], data["description"], source.pk):
            raise RuntimeError("Задача с таким slug уже существует с другими данными; она не перезаписана.")
        task.tags.add(tag)
        placement, _ = TaskPlacement.objects.get_or_create(task=task, task_type=typ, defaults={"status": "draft"})
        answer_field = TaskAnswerForm(task.correct_answer).answer_fields[0].name
        answer_form = TaskAnswerForm(task.correct_answer, data={answer_field: "16"})
        assert answer_form.is_valid(), answer_form.errors
        assert grade_answer("binary", task.correct_answer, answer_form.get_answer(), max_score=1) == (1, True)
        assert grade_answer("binary", task.correct_answer, 15, max_score=1) == (0, False)
        validation = validate_rollover(exam)
        if any(data["tag"] in message for message in validation["errors"]):
            raise RuntimeError("Замечание по новому тегу не устранено.")
        info = exam.publication_info.copy()
        info["pending_review"] = [item for item in info.get("pending_review", []) if item != "Задачи для темы «Замена цифр»"]
        if info != exam.publication_info:
            exam.publication_info = info
            exam.save(update_fields=["publication_info", "updated_at"])
        after = retained_data_fingerprint(exam.copied_from)
        for key in before.keys() - {"tasks", "task_tags"}:
            if before[key] != after[key]:
                raise RuntimeError(f"Неожиданное изменение сохранённых данных: {key}.")
        if after["tasks"]["count"] != before["tasks"]["count"] + int(created):
            raise RuntimeError("Неожиданное изменение количества задач.")
        report = {"created": created, "task_id": task.pk, "task_slug": task.slug, "exam_id": exam.pk,
                  "type_id": typ.pk, "tag_id": tag.pk, "placement_status": placement.status,
                  "correct_answer": task.correct_answer, "history_and_mastery_unchanged": True,
                  "publication_ready": validation["ready"], "remaining_errors": validation["errors"]}
    report_path = ROOT / ".local/exam-sandbox/transition-2027/demo13-added.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
