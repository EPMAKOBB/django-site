import json
from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.recsys.models import Attempt, ExamVersion, Subject, Task, TaskTag, TaskType, TrainingDraft, VariantAttempt


class TrainingBuilderTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="builder-student")
        self.client.force_login(self.user)
        subject = Subject.objects.create(name="Builder subject")
        self.exam = ExamVersion.objects.create(name="Builder exam", slug="builder-exam", subject=subject)
        self.type = TaskType.objects.create(name="Type 1", slug="type-1", exam_version=self.exam, subject=subject)
        self.tag = TaskTag.objects.create(name="Logic", slug="builder-logic", subject=subject)
        self.type.required_tags.add(self.tag)
        self.tasks = [Task.objects.create(title=f"Task {i}", description=f"Question {i}", type=self.type,
                                          subject=subject, exam_version=self.exam, status="published", correct_answer={"value":"42"}) for i in range(6)]
        for task in self.tasks[:3]:
            task.tags.add(self.tag)
        self.url = f"/api/exams/{self.exam.pk}/training-draft/"

    def post(self, data, *, status=200):
        revision = self.client.get(self.url).json()["revision"]
        response = self.client.post(self.url, json.dumps({"revision":revision, **data}), content_type="application/json")
        self.assertEqual(response.status_code, status, response.content)
        return response.json()

    def start(self, count=2):
        self.post({"action":"count", "type_id":self.type.pk, "count":count})
        result = self.post({"action":"start"})
        return VariantAttempt.objects.get(pk=result["attempt_id"])

    def archive(self, work, archived=True, **extra):
        state = self.client.get(f"/api/variants/attempts/{work.pk}/state/").json()
        return self.client.post(f"/api/variants/attempts/{work.pk}/archive/", json.dumps({
            "archived":archived, "lifecycle_revision":state.get("lifecycle_revision", 0),
            "operation_id":str(uuid4()), **extra,
        }), content_type="application/json")

    def check(self, work, row, answer, key=None):
        work.refresh_from_db()
        return self.client.post(f"/api/variants/attempts/{work.pk}/tasks/{row.pk}/check/",
                                json.dumps({"answer":answer, "submission_key":str(key or uuid4())}), content_type="application/json", HTTP_X_TRAINING_REVISION=str(work.training_revision))

    def test_selection_is_persistent_and_same_tasks_are_checked_on_type_page(self):
        payload = self.post({"action":"count", "type_id":self.type.pk, "count":5})
        self.assertEqual(payload["count"], 5)
        self.assertEqual(len({s["task_id"] for s in payload["selections"]}), 5)
        another_session = Client()
        another_session.force_login(self.user)
        self.assertEqual(another_session.get(self.url).json()["selections"], payload["selections"])
        self.assertContains(self.client.get("/exams/builder-exam/type-1/"), "data-training-task", status_code=200)

    def test_manual_choices_survive_recommendation_and_lowering_count(self):
        self.post({"action":"toggle", "task_id":self.tasks[0].pk, "type_id":self.type.pk, "selected":True})
        data = self.post({"action":"recommend", "count":4})
        self.assertTrue(next(s for s in data["selections"] if s["task_id"] == self.tasks[0].pk)["manual"])
        self.post({"action":"count", "type_id":self.type.pk, "count":0}, status=400)
        data = self.post({"action":"count", "type_id":self.type.pk, "count":1})
        self.assertEqual(data["selections"][0]["task_id"], self.tasks[0].pk)

    def test_type_recommendations_keep_other_types_and_fill_only_the_requested_type(self):
        other_type = TaskType.objects.create(name="Other type", subject=self.exam.subject, exam_version=self.exam)
        Task.objects.bulk_create([Task(title=f"Other {n}", description="Question", type=other_type,
            subject=self.exam.subject, exam_version=self.exam, status="published") for n in range(3)])
        before = self.post({"action":"count", "type_id":other_type.pk, "count":2})
        other_ids = {s["task_id"] for s in before["selections"]}
        selected = self.post({"action":"recommend", "type_id":self.type.pk, "count":3})
        self.assertEqual(sum(s["type_id"] == self.type.pk for s in selected["selections"]), 3)
        self.assertEqual({s["task_id"] for s in selected["selections"] if s["type_id"] == other_type.pk}, other_ids)
        self.assertEqual(selected["count"], 5)

    def test_type_recommendations_reject_a_foreign_exam_type(self):
        other_exam = ExamVersion.objects.create(name="Foreign", subject=self.exam.subject)
        foreign_type = TaskType.objects.create(name="Foreign type", subject=self.exam.subject, exam_version=other_exam)
        self.post({"action":"recommend", "type_id":foreign_type.pk, "count":3}, status=400)
        self.assertEqual(self.client.get(self.url).json()["count"], 0)

    def test_type_recommendations_respect_the_shared_hundred_task_limit(self):
        Task.objects.bulk_create([Task(title=f"Extra {n}", description="Question", type=self.type,
            subject=self.exam.subject, exam_version=self.exam, status="published") for n in range(89)])
        other_type = TaskType.objects.create(name="Other type", subject=self.exam.subject, exam_version=self.exam)
        Task.objects.bulk_create([Task(title=f"Other {n}", description="Question", type=other_type,
            subject=self.exam.subject, exam_version=self.exam, status="published") for n in range(10)])
        before = self.post({"action":"count", "type_id":self.type.pk, "count":95})
        selected = self.post({"action":"recommend", "type_id":other_type.pk, "count":10})
        self.assertEqual(selected["count"], 100)
        self.assertTrue({s["task_id"] for s in before["selections"]}.issubset({s["task_id"] for s in selected["selections"]}))
        self.assertEqual(sum(s["type_id"] == other_type.pk for s in selected["selections"]), 5)

    def test_type_page_has_compact_tools_and_keeps_staff_drafts_read_only(self):
        draft_task = Task.objects.create(title="Draft question", description="Draft", type=self.type,
            subject=self.exam.subject, exam_version=self.exam, status="draft")
        page = self.client.get("/exams/builder-exam/type-1/")
        self.assertNotContains(page, draft_task.title)
        self.assertEqual(page.context["available_task_count"], 6)
        self.assertContains(page, 'data-view="type"')
        self.assertNotContains(page, 'data-training-works')
        self.assertNotContains(page, 'Моя тренировка')
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        page = self.client.get("/exams/builder-exam/type-1/")
        self.assertContains(page, draft_task.title)
        self.assertEqual(page.context["draft_task_count"], 1)
        self.assertEqual(page.context["task_count"], 7)
        row = next(row for row in page.context["task_rows"] if row["task"].pk == draft_task.pk)
        self.assertFalse(row["can_train"])

    def test_tag_minimum_and_shortage_are_explicit(self):
        data = self.post({"action":"count", "type_id":self.type.pk, "count":5, "tag_minima":{str(self.tag.pk):3}})
        self.assertEqual(data["count"], 5)
        self.assertEqual(data["types"][0]["tags"][0]["count"], 3)
        data = self.post({"action":"count", "type_id":self.type.pk, "count":8})
        self.assertEqual(data["types"][0]["requested"], 8)
        self.assertEqual(data["count"], 6)

    def test_overlapping_tags_count_unique_tasks_once(self):
        other = TaskTag.objects.create(name="Other", slug="builder-other", subject=self.exam.subject)
        self.tasks[0].tags.add(other)
        data = self.post({"action":"count", "type_id":self.type.pk, "count":1,
                          "tag_minima":{str(self.tag.pk):1, str(other.pk):1}})
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["selections"][0]["task_id"], self.tasks[0].pk)

    def test_stale_revision_cannot_overwrite_or_start_twice(self):
        self.post({"action":"count", "type_id":self.type.pk, "count":2})
        revision = self.client.get(self.url).json()["revision"]
        self.post({"action":"start", "revision":revision})
        self.post({"action":"start", "revision":revision}, status=409)
        self.assertEqual(VariantAttempt.objects.count(), 1)

    def test_start_requires_archiving_current_and_preserves_selection(self):
        first = self.start()
        self.assertEqual(first.mode, "training")
        self.assertIsNone(first.exam_snapshot["time_limit_seconds"])
        self.assertEqual(len(first.exam_snapshot["items"]), 2)
        self.assertEqual(self.client.get(self.url).json()["count"], 0)
        self.post({"action":"count", "type_id":self.type.pk, "count":3}, status=409)
        self.post({"action":"start"}, status=409)
        self.assertEqual(self.archive(first).status_code, 200)
        second = self.start(3)
        first.refresh_from_db()
        self.assertIsNotNone(first.archived_at)
        self.assertEqual(len(first.exam_snapshot["items"]), 2)
        works = self.client.get(f"/api/exams/{self.exam.pk}/works/").json()
        self.assertEqual(works["current_training"]["id"], second.pk)
        self.assertEqual([w["id"] for w in works["archive"]["results"]], [first.pk])

    def test_save_check_retry_and_archive_do_not_duplicate_mastery_attempts(self):
        work = self.start()
        row = work.assignment.template.template_tasks.first()
        url = f"/api/variants/attempts/{work.pk}/"
        before = self.client.get(url).json()
        self.assertNotIn("correct_answer", before["tasks_progress"][0]["task_snapshot"])
        key = uuid4()
        response = self.check(work, row, "wrong", key)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn("correct_answer", response.json()["tasks_progress"][0]["task_snapshot"])
        self.assertFalse(response.json()["tasks_progress"][0]["is_completed"])
        self.check(work, row, "wrong", key)
        self.assertEqual(Attempt.objects.count(), 1)
        self.assertEqual(Attempt.objects.get().mode, "training")
        response = self.check(work, row, "42")
        self.assertTrue(response.json()["tasks_progress"][0]["is_completed"])
        self.assertIn("correct_answer", response.json()["tasks_progress"][0]["task_snapshot"])
        response = self.archive(work)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Attempt.objects.count(), 2)
        detail = self.client.get(url).json()
        self.assertEqual(len(detail["tasks_progress"][1]["attempts"]), 0)
        self.assertIsNone(detail["secondary_summary"])
        self.assertEqual(self.client.post(url + "finalize/").status_code, 409)
        self.assertEqual(Attempt.objects.count(), 2)

    def test_late_check_retry_does_not_overwrite_newer_saved_answer(self):
        work = self.start(1)
        row = work.assignment.template.template_tasks.first()
        key = uuid4()
        self.check(work, row, "old", key)
        self.client.post(f"/api/variants/attempts/{work.pk}/tasks/{row.pk}/save/", json.dumps({"answer":"new"}), content_type="application/json")
        replay = self.check(work, row, "old", key)
        self.assertEqual(replay.json()["tasks_progress"][0]["saved_response"], "new")
        self.assertEqual(Attempt.objects.count(), 1)

    def test_archive_does_not_check_unchecked_answer_or_change_mastery(self):
        work = self.start(1)
        row = work.assignment.template.template_tasks.first()
        self.check(work, row, "wrong")
        self.client.post(f"/api/variants/attempts/{work.pk}/tasks/{row.pk}/save/", json.dumps({"answer":"42"}), content_type="application/json")
        self.assertEqual(self.client.post(f"/api/variants/attempts/{work.pk}/finalize/").status_code, 400)
        self.assertEqual(self.archive(work).status_code, 200)
        self.assertEqual(Attempt.objects.count(), 1)
        self.assertFalse(Attempt.objects.get().is_correct)
        self.assertEqual(self.archive(work, False).status_code, 200)
        self.check(work, row, "42")
        self.assertEqual(Attempt.objects.count(), 2)
        self.archive(work)
        self.archive(work, False)
        self.check(work, row, "42")
        self.assertEqual(Attempt.objects.count(), 2)

    def test_archive_restore_and_flag_keep_answers(self):
        work = self.start(1)
        row = work.assignment.template.template_tasks.first()
        self.check(work, row, "wrong")
        url = f"/api/variants/attempts/{work.pk}/"
        response = self.client.post(url + f"tasks/{row.pk}/flag/", json.dumps({"flagged":True}), content_type="application/json")
        self.assertEqual(response.json()["flagged_task_ids"], [row.pk])
        response = self.archive(work)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(f"/api/exams/{self.exam.pk}/works/").json()["archive"]["results"][0]["status"], "archived")
        blocked = self.client.post(url + f"tasks/{row.pk}/save/", json.dumps({"answer":"lost"}), content_type="application/json")
        self.assertEqual(blocked.status_code, 409)
        self.archive(work, False)
        payload = self.client.get(url).json()
        self.assertEqual(payload["tasks_progress"][0]["saved_response"], "wrong")
        self.assertEqual(payload["flagged_task_ids"], [row.pk])

    def test_mistakes_fill_existing_draft_and_do_not_include_correct_tasks(self):
        work = self.start(2)
        first = work.assignment.template.template_tasks.first()
        self.check(work, first, "42")
        self.archive(work)
        data = self.post({"action":"mistakes", "attempt_id":work.pk})
        self.assertEqual(data["count"], 1)
        self.assertNotEqual(data["selections"][0]["task_id"], first.task_id)

    def test_cross_user_and_cross_exam_access_are_rejected(self):
        work = self.start(1)
        other_exam = ExamVersion.objects.create(subject=self.exam.subject, name="Foreign", slug="foreign")
        foreign_url = f"/api/exams/{other_exam.pk}/training-draft/"
        response = self.client.post(foreign_url, json.dumps({"action":"toggle", "revision":0, "task_id":self.tasks[0].pk,
                                                           "type_id":self.type.pk, "selected":True}), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        other = get_user_model().objects.create_user(username="other-builder")
        self.client.force_login(other)
        self.assertEqual(self.client.get(self.url).json()["count"], 0)
        response = self.archive(work)
        self.assertEqual(response.status_code, 404)

    def test_unpublished_and_unavailable_exam_cannot_be_issued(self):
        self.tasks[0].status = "draft"
        self.tasks[0].save()
        self.post({"action":"toggle", "task_id":self.tasks[0].pk, "type_id":self.type.pk, "selected":True}, status=400)
        self.exam.status = "archived"
        self.exam.save()
        self.post({"action":"recommend", "count":2}, status=400)

    def test_draft_post_requires_csrf_with_custom_httponly_cookie(self):
        with override_settings(CSRF_COOKIE_NAME="builder_csrf", CSRF_COOKIE_HTTPONLY=True):
            client = Client(enforce_csrf_checks=True)
            client.force_login(self.user)
            page = client.get("/exams/builder-exam/public/")
            self.assertEqual(page.status_code, 200)
            import re
            token = re.search(r'data-csrf="([A-Za-z0-9]+)"', page.json()["html"]).group(1)
            data = json.dumps({"action":"recommend", "revision":0, "count":2})
            self.assertEqual(client.post(self.url, data, content_type="application/json").status_code, 403)
            self.assertEqual(client.post(self.url, data, content_type="application/json", HTTP_X_CSRFTOKEN=token).status_code, 200)

    def test_pause_stops_time_and_caps_a_closed_browsers_idle_time(self):
        work = self.start(1)
        row = work.assignment.template.template_tasks.first()
        started = timezone.now() - timedelta(hours=12)
        VariantAttempt.objects.filter(pk=work.pk).update(active_variant_task=row, active_started_at=started, last_seen_at=started)
        response = self.client.post(f"/api/variants/attempts/{work.pk}/pause/")
        self.assertEqual(response.status_code, 200)
        work.refresh_from_db()
        self.assertIsNone(work.active_variant_task_id)
        self.assertEqual(work.time_logs.get().duration, timedelta(seconds=90))
        self.archive(work)
        work.refresh_from_db()
        self.assertEqual(work.time_logs.get().duration, timedelta(seconds=90))

    def test_cleared_answer_is_unanswered_and_does_not_reduce_mastery(self):
        work = self.start(1)
        row = work.assignment.template.template_tasks.first()
        url = f"/api/variants/attempts/{work.pk}/"
        for answer in ["42", ""]:
            response = self.client.post(url + f"tasks/{row.pk}/save/", json.dumps({"answer":answer}), content_type="application/json")
            self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["tasks_progress"][0]["saved_response"])
        self.assertEqual(self.check(work, row, "").status_code, 400)
        self.archive(work)
        self.assertEqual(Attempt.objects.count(), 0)

    def test_restore_swaps_current_and_keeps_answers_and_flags(self):
        first = self.start(2)
        row = first.assignment.template.template_tasks.first()
        self.check(first, row, "42")
        self.archive(first)
        second = self.start(1)
        result = self.archive(first, False)
        self.assertEqual(result.status_code, 200, result.content)
        first.refresh_from_db(); second.refresh_from_db()
        self.assertIsNone(first.archived_at)
        self.assertIsNotNone(second.archived_at)
        self.assertEqual(Attempt.objects.count(), 1)
        payload = self.client.get(f"/api/variants/attempts/{first.pk}/").json()
        self.assertEqual(payload["tasks_progress"][0]["saved_response"], "42")
        self.check(first, row, "42")
        self.assertEqual(Attempt.objects.count(), 1)

    def test_old_lifecycle_request_and_late_retry_cannot_switch_back(self):
        first = self.start(1)
        state = self.client.get(f"/api/variants/attempts/{first.pk}/state/").json()
        body = {"archived":True, "lifecycle_revision":state["lifecycle_revision"], "operation_id":str(uuid4())}
        endpoint = f"/api/variants/attempts/{first.pk}/archive/"
        original = self.client.post(endpoint, json.dumps(body), content_type="application/json")
        self.archive(first, False)
        replay = self.client.post(endpoint, json.dumps(body), content_type="application/json")
        self.assertEqual(replay.json(), original.json())
        first.refresh_from_db()
        self.assertIsNone(first.archived_at)
        body["operation_id"] = str(uuid4())
        self.assertEqual(self.client.post(endpoint, json.dumps(body), content_type="application/json").status_code, 409)
        self.assertIsNone(VariantAttempt.objects.get(pk=first.pk).archived_at)

    def test_start_receipt_survives_a_lost_response(self):
        self.post({"action":"count", "type_id":self.type.pk, "count":1})
        draft = self.client.get(self.url).json()
        body = {"action":"start", "revision":draft["revision"], "lifecycle_revision":draft["lifecycle_revision"], "operation_id":str(uuid4())}
        first = self.client.post(self.url, json.dumps(body), content_type="application/json")
        repeat = self.client.post(self.url, json.dumps(body), content_type="application/json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), repeat.json())
        self.assertEqual(VariantAttempt.objects.count(), 1)

    def test_repeated_unchanged_check_receipt_cannot_overwrite_a_later_answer(self):
        work = self.start(1)
        row = work.assignment.template.template_tasks.first()
        self.check(work, row, "42")
        key = uuid4()
        self.check(work, row, "42", key)
        self.check(work, row, "wrong")
        replay = self.check(work, row, "42", key)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["tasks_progress"][0]["saved_response"], "wrong")
        self.assertEqual(Attempt.objects.count(), 2)

    def test_all_correct_work_stays_current_until_explicit_archive(self):
        work = self.start(1)
        row = work.assignment.template.template_tasks.first()
        self.check(work, row, "42")
        works = self.client.get(f"/api/exams/{self.exam.pk}/works/").json()
        self.assertEqual(works["current_training"]["correct"], 1)
        self.assertEqual(works["archive"]["count"], 0)
        self.archive(work)
        self.assertEqual(Attempt.objects.count(), 1)

    def test_current_training_in_another_exam_is_independent(self):
        first = self.start(1)
        exam = ExamVersion.objects.create(name="Another exam", subject=self.exam.subject)
        task_type = TaskType.objects.create(name="Other type", subject=self.exam.subject, exam_version=exam)
        Task.objects.create(title="Other task", description="Question", subject=self.exam.subject, type=task_type,
                            exam_version=exam, status="published", correct_answer={"value":"42"})
        endpoint = f"/api/exams/{exam.pk}/training-draft/"
        draft = self.client.get(endpoint).json()
        selected = self.client.post(endpoint, json.dumps({"action":"count", "revision":draft["revision"],
            "type_id":task_type.pk, "count":1}), content_type="application/json").json()
        started = self.client.post(endpoint, json.dumps({"action":"start", "revision":selected["revision"]}), content_type="application/json")
        self.assertEqual(started.status_code, 200, started.content)
        self.archive(first)
        other = VariantAttempt.objects.get(pk=started.json()["attempt_id"])
        self.assertIsNone(other.archived_at)

    def test_maximum_one_hundred_tasks_can_be_started(self):
        Task.objects.bulk_create([Task(title=f"Extra task {n}", description="Question", type=self.type,
            subject=self.exam.subject, exam_version=self.exam, status="published", correct_answer={"value":"42"}) for n in range(94)])
        work = self.start(100)
        self.assertEqual(len(work.exam_snapshot["items"]), 100)
        self.assertEqual(work.task_attempts.count(), 100)

    def test_stale_solver_requests_fail_even_after_restoring_the_same_work(self):
        work = self.start(1)
        row = work.assignment.template.template_tasks.first()
        self.archive(work); self.archive(work, False)
        base = f"/api/variants/attempts/{work.pk}/"
        for suffix, data in [(f"tasks/{row.pk}/save/", {"answer":"old"}),
                             (f"tasks/{row.pk}/focus/", {}), ("heartbeat/", {}), ("pause/", {}),
                             (f"tasks/{row.pk}/flag/", {"flagged":True})]:
            response = self.client.post(base+suffix, json.dumps(data), content_type="application/json", HTTP_X_TRAINING_REVISION="0")
            self.assertEqual(response.status_code, 409, (suffix, response.content))
        work.refresh_from_db()
        self.assertIsNone(work.active_variant_task_id)
        self.assertEqual(Attempt.objects.count(), 0)

    def test_conflicting_local_answer_does_not_overwrite_server_answer(self):
        work = self.start(1)
        row = work.assignment.template.template_tasks.first()
        endpoint = f"/api/variants/attempts/{work.pk}/tasks/{row.pk}/save/"
        self.client.post(endpoint, json.dumps({"answer":"new"}), content_type="application/json")
        response = self.client.post(endpoint, json.dumps({"answer":"local", "expected_answer":None}), content_type="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(work.task_attempts.get(attempt_number=0).task_snapshot["response"]["value"], "new")

    def test_archive_is_paginated_without_exposing_conditions_or_other_users(self):
        work = self.start(1)
        self.archive(work)
        VariantAttempt.objects.bulk_create([VariantAttempt(assignment=work.assignment, attempt_number=n,
            mode="training", archived_at=timezone.now(), exam_snapshot=work.exam_snapshot) for n in range(2, 56)])
        endpoint = f"/api/exams/{self.exam.pk}/works/"
        first = self.client.get(endpoint).json()
        second = self.client.get(endpoint+"?page=2").json()
        self.assertEqual(first["archive"]["count"], 55)
        self.assertEqual(len(first["archive"]["results"]), 20)
        self.assertEqual(len(second["archive"]["results"]), 20)
        self.assertFalse({w["id"] for w in first["archive"]["results"]} & {w["id"] for w in second["archive"]["results"]})
        self.assertNotIn("task_snapshot", json.dumps(first))
        self.assertNotIn("correct_answer", json.dumps(first))
        self.assertEqual(self.client.get(endpoint+"?page=999999").json()["archive"]["page"], 3)
        self.assertEqual(self.client.get(endpoint+"?page=bad").status_code, 200)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from apps.recsys.service_utils.training_builder import works_payload
        with CaptureQueriesContext(connection) as queries:
            works_payload(self.user, self.exam, page=2)
        self.assertLessEqual(len(queries), 12)

    def test_limits_reject_oversize_requests_and_corrupt_drafts(self):
        self.post({"action":"count", "type_id":self.type.pk, "count":1000}, status=400)
        with override_settings(TRAINING_REQUEST_MAX_BYTES=80):
            self.post({"action":"toggle", "task_id":self.tasks[0].pk, "type_id":self.type.pk, "selected":True}, status=400)
        draft = TrainingDraft.objects.get(user=self.user, exam_version=self.exam)
        entry = {"task_id":self.tasks[0].pk, "type_id":self.type.pk, "manual":True}
        draft.selections = [entry]*101
        draft.save()
        self.post({"action":"start"}, status=400)
        self.assertEqual(VariantAttempt.objects.count(), 0)
        draft.selections = [entry, entry]; draft.save()
        self.post({"action":"start"}, status=400)

    def test_training_request_limit_does_not_change_exam_saves(self):
        work = self.start(1)
        VariantAttempt.objects.filter(pk=work.pk).update(mode="exam")
        row = work.assignment.template.template_tasks.first()
        with override_settings(TRAINING_REQUEST_MAX_BYTES=20):
            response = self.client.post(f"/api/variants/attempts/{work.pk}/tasks/{row.pk}/save/",
                json.dumps({"answer":"A long exam answer beyond the training test limit"}), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)

    def test_creation_rate_limit_keeps_draft(self):
        work = self.start(1); self.archive(work)
        self.post({"action":"count", "type_id":self.type.pk, "count":2})
        with override_settings(TRAINING_CREATE_LIMIT=1):
            self.post({"action":"start"}, status=429)
        self.assertEqual(self.client.get(self.url).json()["count"], 2)
        self.assertEqual(VariantAttempt.objects.count(), 1)

    def test_generation_failure_rolls_back_creation_and_preserves_draft(self):
        from unittest.mock import patch
        from rest_framework.exceptions import ValidationError
        self.post({"action":"count", "type_id":self.type.pk, "count":2})
        with patch("apps.recsys.service_utils.variants._materialize_tasks_for_attempt", side_effect=ValidationError("Generation failed")):
            self.post({"action":"start"}, status=400)
        self.assertEqual(VariantAttempt.objects.count(), 0)
        self.assertEqual(self.client.get(self.url).json()["count"], 2)

    def test_archive_view_does_not_activate_and_restore_uses_frozen_tasks(self):
        work = self.start(1); self.archive(work)
        # Resolve the actual URL rather than depending on the dashboard path.
        from django.urls import reverse
        page = self.client.get(reverse("accounts:variant-attempt-solver", args=[work.pk]))
        self.assertEqual(page.status_code, 200)
        work.refresh_from_db(); self.assertIsNotNone(work.archived_at)
        self.exam.status = "archived"; self.exam.save()
        self.tasks[0].status = "draft"; self.tasks[0].save()
        self.assertEqual(self.archive(work, False).status_code, 200)
        self.assertEqual(self.client.get(f"/api/variants/attempts/{work.pk}/").status_code, 200)


class TrainingConcurrencyTests(TransactionTestCase):
    setUp = TrainingBuilderTests.setUp
    post = TrainingBuilderTests.post
    start = TrainingBuilderTests.start
    archive = TrainingBuilderTests.archive

    def parallel(self, calls):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        from rest_framework.exceptions import APIException
        barrier = Barrier(len(calls))
        def run(call):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                try:
                    return (200, call())
                except APIException as exc:
                    return (exc.status_code, None)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            futures = [pool.submit(run, call) for call in calls]
            return [future.result(timeout=15) for future in futures]

    def test_two_simultaneous_starts_create_one_work(self):
        from apps.recsys.service_utils.training_builder import change_draft
        self.post({"action":"count", "type_id":self.type.pk, "count":2})
        revision = TrainingDraft.objects.get(user=self.user, exam_version=self.exam).revision
        def launch():
            return change_draft(self.user, self.exam, {"action":"start", "revision":revision})
        results = self.parallel([launch, launch])
        self.assertEqual(sorted(code for code, _ in results), [200, 409])
        self.assertEqual(VariantAttempt.objects.filter(mode="training", archived_at__isnull=True).count(), 1)

    def test_two_restores_cannot_both_succeed_from_the_same_state(self):
        from apps.recsys.service_utils.training_builder import archive_work
        first = self.start(1); self.archive(first)
        second = self.start(1); self.archive(second)
        current = self.start(1)
        revision = TrainingDraft.objects.get(user=self.user, exam_version=self.exam).lifecycle_revision
        results = self.parallel([
            lambda: archive_work(self.user, first.pk, False, lifecycle_revision=revision, operation_id=uuid4()),
            lambda: archive_work(self.user, second.pk, False, lifecycle_revision=revision, operation_id=uuid4()),
        ])
        self.assertEqual(sorted(code for code, _ in results), [200, 409])
        self.assertEqual(VariantAttempt.objects.filter(mode="training", archived_at__isnull=True).count(), 1)
        current.refresh_from_db(); self.assertIsNotNone(current.archived_at)

    def test_check_and_archive_serialize_without_losing_a_successful_check(self):
        from apps.recsys.service_utils.training_builder import archive_work
        work = self.start(1)
        row = work.assignment.template.template_tasks.first()
        revision = TrainingDraft.objects.get(user=self.user, exam_version=self.exam).lifecycle_revision
        def check():
            client = Client(); client.force_login(self.user)
            result = client.post(f"/api/variants/attempts/{work.pk}/tasks/{row.pk}/check/", json.dumps(
                {"answer":"42", "submission_key":str(uuid4())}), content_type="application/json", HTTP_X_TRAINING_REVISION="0")
            return result.status_code
        results = self.parallel([check, lambda: archive_work(self.user, work.pk, True, lifecycle_revision=revision, operation_id=uuid4())])
        check_status = results[0][1]
        self.assertIn(check_status, [200, 409])
        self.assertEqual(Attempt.objects.count(), 1 if check_status == 200 else 0)
        work.refresh_from_db(); self.assertIsNotNone(work.archived_at)
