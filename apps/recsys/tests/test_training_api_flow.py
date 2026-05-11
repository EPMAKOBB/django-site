import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.recsys.models import Attempt, ExamVersion, Subject, Task, TaskTag, TaskType, TrainingSession


class TrainingApiFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="training-user")
        self.client.force_login(self.user)
        self.subject = Subject.objects.create(name="Subject")
        self.other_subject = Subject.objects.create(name="Other subject")
        self.exam_version = ExamVersion.objects.create(
            name="V1",
            subject=self.subject,
        )
        self.other_exam_version = ExamVersion.objects.create(
            name="V2",
            subject=self.other_subject,
        )
        self.task_type = TaskType.objects.create(
            name="Type",
            subject=self.subject,
            exam_version=self.exam_version,
        )
        self.other_task_type = TaskType.objects.create(
            name="Other Type",
            subject=self.other_subject,
            exam_version=self.other_exam_version,
        )
        self.tag = TaskTag.objects.create(
            subject=self.subject,
            name="Tag",
            slug="tag",
        )
        self.other_tag = TaskTag.objects.create(
            subject=self.other_subject,
            name="Other Tag",
            slug="other-tag",
        )
        self.task_type.required_tags.add(self.tag)
        self.other_task_type.required_tags.add(self.other_tag)
        self.task1 = Task.objects.create(
            type=self.task_type,
            title="Task 1",
            subject=self.subject,
            exam_version=self.exam_version,
            correct_answer={"value": "42"},
        )
        self.task1.tags.add(self.tag)
        self.task2 = Task.objects.create(
            type=self.task_type,
            title="Task 2",
            subject=self.subject,
            exam_version=self.exam_version,
            correct_answer={"value": "43"},
        )
        self.task2.tags.add(self.tag)
        self.foreign_task = Task.objects.create(
            type=self.other_task_type,
            title="Foreign task",
            subject=self.other_subject,
            exam_version=self.other_exam_version,
            correct_answer={"value": "99"},
        )
        self.foreign_task.tags.add(self.other_tag)
        Task.objects.update(status=Task.Status.PUBLISHED)

    def test_training_session_start_submit_and_end(self):
        resp = self.client.get(
            "/api/training/sessions/current/",
            {"exam_version_id": self.exam_version.id},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["session"])
        self.assertEqual(resp.json()["selected_task_types"], [])

        resp = self.client.post(
            "/api/training/sessions/",
            data=json.dumps({"exam_version_id": self.exam_version.id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        payload = resp.json()
        self.assertEqual(payload["session"]["status"], "active")
        self.assertEqual(
            set(payload["session"]["selected_task_type_ids"]),
            {self.task_type.id},
        )
        self.assertEqual(payload["session"]["steps_total"], 1)
        current_task = payload["current_task"]
        self.assertIsNotNone(current_task)
        self.assertIn(current_task["task_id"], {self.task1.id, self.task2.id})
        self.assertEqual(len(payload["history"]), 1)
        session_id = payload["session"]["id"]
        step_id = current_task["step_id"]
        correct_value = "42" if current_task["task_id"] == self.task1.id else "43"

        resp = self.client.get(
            "/api/training/sessions/current/",
            {"exam_version_id": self.exam_version.id},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["session"]["id"], session_id)

        resp = self.client.post(
            f"/api/training/sessions/{session_id}/submit/",
            data=json.dumps({"step_id": step_id, "answer": {"value": correct_value}}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        submit_payload = resp.json()
        self.assertEqual(submit_payload["submission_result"]["step_id"], step_id)
        self.assertTrue(submit_payload["submission_result"]["is_correct"])
        self.assertEqual(submit_payload["session"]["completed_steps"], 1)
        self.assertEqual(len(submit_payload["history"]), 1)
        self.assertEqual(submit_payload["current_task"]["step_id"], step_id)
        answered_step = next(item for item in submit_payload["history"] if item["id"] == step_id)
        self.assertEqual(answered_step["status"], "answered")

        resp = self.client.post(
            f"/api/training/sessions/{session_id}/next/",
            data=json.dumps({"step_id": step_id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        next_payload = resp.json()
        self.assertEqual(next_payload["session"]["steps_total"], 2)
        self.assertIsNotNone(next_payload["current_task"])
        self.assertNotEqual(next_payload["current_task"]["step_id"], step_id)

        resp = self.client.post(f"/api/training/sessions/{session_id}/end/")
        self.assertEqual(resp.status_code, 200)
        end_payload = resp.json()
        self.assertEqual(end_payload["session"]["status"], "completed")
        session = TrainingSession.objects.get(pk=session_id)
        self.assertEqual(session.status, TrainingSession.Status.COMPLETED)

    def test_training_session_never_recommends_task_from_other_exam_version(self):
        resp = self.client.post(
            "/api/training/sessions/",
            data=json.dumps({"exam_version_id": self.exam_version.id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        payload = resp.json()
        current_task = payload["current_task"]
        self.assertIsNotNone(current_task)
        self.assertNotEqual(current_task["task_id"], self.foreign_task.id)

        session_id = payload["session"]["id"]
        step_id = current_task["step_id"]
        correct_value = "42" if current_task["task_id"] == self.task1.id else "43"
        resp = self.client.post(
            f"/api/training/sessions/{session_id}/submit/",
            data=json.dumps({"step_id": step_id, "answer": {"value": correct_value}}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        resp = self.client.post(
            f"/api/training/sessions/{session_id}/next/",
            data=json.dumps({"step_id": step_id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        next_task = resp.json()["current_task"]
        if next_task is not None:
            self.assertNotEqual(next_task["task_id"], self.foreign_task.id)

    def test_type_filters_endpoint_and_selected_type_validation(self):
        resp = self.client.get(
            "/api/training/type-filters/",
            {"exam_version_id": self.exam_version.id},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn("summary", payload)
        self.assertEqual(payload["recommended_type_ids"], [self.task_type.id])
        self.assertEqual(len(payload["types"]), 1)
        self.assertEqual(payload["types"][0]["type_id"], self.task_type.id)
        self.assertTrue(payload["types"][0]["selected_by_default"])

        resp = self.client.post(
            "/api/training/sessions/",
            data=json.dumps(
                {
                    "exam_version_id": self.exam_version.id,
                    "selected_task_type_ids": [self.foreign_task.type_id],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("selected_task_type_ids", resp.json())

    def test_training_session_respects_selected_task_types(self):
        extra_type = TaskType.objects.create(
            name="Second Type",
            subject=self.subject,
            exam_version=self.exam_version,
        )
        extra_task = Task.objects.create(
            type=extra_type,
            title="Extra task",
            subject=self.subject,
            exam_version=self.exam_version,
            correct_answer={"value": "100"},
            status=Task.Status.PUBLISHED,
        )

        resp = self.client.post(
            "/api/training/sessions/",
            data=json.dumps(
                {
                    "exam_version_id": self.exam_version.id,
                    "selected_task_type_ids": [extra_type.id],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        payload = resp.json()
        self.assertEqual(payload["session"]["selected_task_type_ids"], [extra_type.id])
        self.assertEqual(payload["current_task"]["task_id"], extra_task.id)

    def test_training_session_completes_when_selected_pool_is_exhausted(self):
        extra_type = TaskType.objects.create(
            name="Single Task Type",
            subject=self.subject,
            exam_version=self.exam_version,
        )
        task = Task.objects.create(
            type=extra_type,
            title="Only task",
            subject=self.subject,
            exam_version=self.exam_version,
            correct_answer={"value": "100"},
            status=Task.Status.PUBLISHED,
        )

        resp = self.client.post(
            "/api/training/sessions/",
            data=json.dumps(
                {
                    "exam_version_id": self.exam_version.id,
                    "selected_task_type_ids": [extra_type.id],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        payload = resp.json()
        self.assertEqual(payload["current_task"]["task_id"], task.id)
        session_id = payload["session"]["id"]
        step_id = payload["current_task"]["step_id"]

        resp = self.client.post(
            f"/api/training/sessions/{session_id}/submit/",
            data=json.dumps({"step_id": step_id, "answer": {"value": "100"}}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        payload = resp.json()
        self.assertEqual(payload["session"]["status"], TrainingSession.Status.ACTIVE)
        self.assertEqual(payload["current_task"]["step_id"], step_id)
        self.assertIsNone(payload["next_step_id"])
        self.assertEqual(len(payload["history"]), 1)

        resp = self.client.post(
            f"/api/training/sessions/{session_id}/next/",
            data=json.dumps({"step_id": step_id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        payload = resp.json()
        self.assertEqual(payload["session"]["status"], TrainingSession.Status.COMPLETED)
        self.assertIsNone(payload["current_task"])
        self.assertIsNone(payload["next_step_id"])
        self.assertEqual(len(payload["history"]), 1)

        sessions_count = TrainingSession.objects.count()
        resp = self.client.post(
            "/api/training/sessions/",
            data=json.dumps(
                {
                    "exam_version_id": self.exam_version.id,
                    "selected_task_type_ids": [extra_type.id],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("selected_task_type_ids", resp.json())
        self.assertEqual(TrainingSession.objects.count(), sessions_count)

    def test_training_session_allows_retry_before_next_task(self):
        resp = self.client.post(
            "/api/training/sessions/",
            data=json.dumps({"exam_version_id": self.exam_version.id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        payload = resp.json()
        session_id = payload["session"]["id"]
        current_task = payload["current_task"]
        step_id = current_task["step_id"]
        correct_value = "42" if current_task["task_id"] == self.task1.id else "43"

        resp = self.client.post(
            f"/api/training/sessions/{session_id}/submit/",
            data=json.dumps({"step_id": step_id, "answer": {"value": "wrong"}}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        first_payload = resp.json()
        self.assertFalse(first_payload["submission_result"]["is_correct"])
        self.assertEqual(first_payload["session"]["completed_steps"], 0)
        self.assertEqual(first_payload["current_task"]["step_id"], step_id)
        self.assertEqual(
            next(item for item in first_payload["history"] if item["id"] == step_id)["status"],
            "opened",
        )

        resp = self.client.post(
            f"/api/training/sessions/{session_id}/submit/",
            data=json.dumps({"step_id": step_id, "answer": {"value": correct_value}}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        second_payload = resp.json()
        self.assertTrue(second_payload["submission_result"]["is_correct"])
        self.assertEqual(second_payload["session"]["completed_steps"], 1)
        self.assertEqual(second_payload["session"]["correct_steps"], 1)
        self.assertEqual(Attempt.objects.filter(user=self.user, task_id=current_task["task_id"]).count(), 2)
        self.assertEqual(Attempt.objects.filter(user=self.user, task_id=current_task["task_id"]).order_by("attempt_number").last().attempt_number, 2)
