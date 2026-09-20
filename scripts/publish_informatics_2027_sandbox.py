"""Verify a complete 2027 variant, then optionally publish in the LOCAL sandbox.

Use --apply to persist publication; all test users, answers and training sessions
always roll back. Does not change any student's selected exam or the 2026 bank.
"""
import argparse
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    os.environ["DJANGO_SETTINGS_MODULE"] = "fractalschool.exam_sandbox_settings"
    import django
    django.setup()
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.db import transaction
    from django.test import Client
    from apps.recsys.models import ExamVersion, Task, TaskAttachment, TaskPlacement, Attempt
    from apps.recsys.service_utils import variants, training
    from apps.recsys.service_utils.exam_rollover import publish_exam, validate_rollover
    from scripts.prepare_informatics_2027 import retained_data_fingerprint

    db = settings.DATABASES["default"]
    if (db["HOST"], str(db["PORT"]), db["NAME"]) != ("127.0.0.1", "55438", "exam_year_sandbox"):
        raise RuntimeError("Разрешена только локальная exam_year_sandbox:55438.")
    with transaction.atomic():
        exam = ExamVersion.objects.select_for_update().get(slug="inf-ege-2027")
        before = retained_data_fingerprint(exam.copied_from)
        if not exam.published_at:
            exam.publication_info.update(
                requirements_checked=True, scale_checked=True, pending_review=[],
                source_document="Локальная проверка 20.09.2026: проект ФИПИ 21.08.2026, СПЕЦ и ДЕМО 2027. Уточнение центра кластера согласовано пользователем. Шкала перевода отключена.",
                limitations=["Проект спецификации, не окончательный документ", "Начальный банк нового типа 23: только кратчайший путь", "Перевод во вторичные баллы отключён до проверки шкалы"],
            )
            exam.save()
        report = validate_rollover(exam)
        if not report["ready"]:
            raise RuntimeError(report["errors"])
        items = list(exam.blueprint.items.select_related("task_type"))
        assert len(items) == 27
        assert {i.order for i in items} == set(range(1, 28))
        assert all(i.task_type.slug == str(i.order) and i.count == 1 for i in items)
        assert sum(i.count * (i.score_override or i.task_type.max_score) for i in items) == 29
        assert not exam.score_scale.is_active
        exam = publish_exam(exam, make_default=True)
        assert ExamVersion.objects.get(pk=exam.copied_from_id).status == "active"
        assert not TaskPlacement.objects.filter(task_type__exam_version=exam, task_type__slug="27", status="active", task__exam_version=exam.copied_from).exists()
        # Exercise real services, but leave no artificial answers or pupils behind.
        with transaction.atomic():
            user = get_user_model().objects.create_user(username=f"local-2027-check-{uuid4().hex}")
            assignment = variants.build_personal_assignment_from_blueprint(user=user, exam_version=exam)
            work = variants.start_new_attempt(user, assignment.pk)
            issued = variants.build_tasks_progress(work)
            assert len(issued) == len({row["task_id"] for row in issued}) == 27
            assert sum(row["task_snapshot"]["max_score"] for row in issued) == 29
            checked_types = []
            for number in (10, 13, 16, 23, 24, 26, 27):
                typ = exam.task_types.get(slug=str(number))
                row = next(r for r in issued if r["task_snapshot"]["context"]["task_type_id"] == typ.pk)
                snapshot = row["task_snapshot"]
                answer = snapshot["correct_answer"]
                if number in (26, 27):
                    assert len(answer) == 2 and all(isinstance(v, int) for v in answer)
                    assert snapshot["answer_schema"]["config"]["rows"] == 1
                    swapped = variants.submit_task_answer(user, work.pk, row["variant_task_id"], is_correct=False, task_snapshot={"answer": answer[::-1]})
                    assert swapped.task_attempt.score == (2 if answer[0] == answer[1] else 1)
                result = variants.submit_task_answer(user, work.pk, row["variant_task_id"], is_correct=True, task_snapshot={"answer": answer})
                assert result.task_attempt.score == snapshot["max_score"], (number, answer, result.task_attempt.score, snapshot["scoring_scheme"])
                assert Attempt.objects.filter(user=user, task_type=typ, exam_version=exam).exists()
                learner = get_user_model().objects.create_user(username=f"local-training-{uuid4().hex}")
                session = training.start_session(learner, exam_version=exam, selected_task_type_ids=[typ.pk])
                step = session.steps.first()
                assert step.placement.task_type_id == typ.pk
                training.submit_step_answer(learner, session_id=session.pk, step_id=step.pk, answer=step.task_snapshot["correct_answer"])
                checked_types.append(number)
            admin = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
            client = Client(HTTP_HOST="127.0.0.1")
            client.force_login(admin)
            paths = [f"/admin/recsys/examversion/{exam.pk}/change/", f"/admin/recsys/examversion/{exam.pk}/review-year/", "/exams/inf-ege-2027/"]
            responses = {path: client.get(path).status_code for path in paths}
            assert all(code == 200 for code in responses.values()), responses
            transaction.set_rollback(True)
        new_tasks = Task.objects.filter(exam_version=exam)
        new_attachments = TaskAttachment.objects.filter(task__in=new_tasks)
        assert new_attachments.count() >= 4
        assert all(a.file.storage.exists(a.file.name) for a in new_attachments)
        all_attachments = TaskAttachment.objects.filter(task__placements__task_type__exam_version=exam, task__placements__status="active").distinct()
        missing = [a.pk for a in all_attachments if not a.file.storage.exists(a.file.name)]
        assert retained_data_fingerprint(exam.copied_from) == before
        result = {"applied": args.apply, "exam_id": exam.pk, "status": exam.status,
                  "is_default": exam.is_default, "tasks_per_variant": 27, "max_primary": 29,
                  "secondary_scale_active": False, "checked_types": checked_types,
                  "old_history_and_bank_unchanged": True, "http_statuses": responses,
                  "new_attachment_count": new_attachments.count(), "missing_legacy_attachment_ids": missing,
                  "validation": report}
        if not args.apply:
            transaction.set_rollback(True)
    path = ROOT / ".local/exam-sandbox/transition-2027/publication-completion.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in {"validation", "missing_legacy_attachment_ids"}}, ensure_ascii=False, indent=2))
    print(f"Отсутствуют старые вложения: {len(missing)}. Полный список в локальном отчёте.")


if __name__ == "__main__":
    main()
