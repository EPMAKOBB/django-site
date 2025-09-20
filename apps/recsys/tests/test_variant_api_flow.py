import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.recsys.models import VariantAttempt
from . import factories


class VariantApiFlowTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="student", password="pass")
        self.client.force_login(self.user)

        self.template = factories.create_variant_template(max_attempts=2, time_limit_minutes=5)
        first_task = factories.create_task()
        second_task = factories.create_task(subject=first_task.subject)
        self.variant_task_1 = factories.add_variant_task(
            template=self.template,
            task=first_task,
            order=1,
            max_attempts=2,
        )
        self.variant_task_2 = factories.add_variant_task(
            template=self.template,
            task=second_task,
            order=2,
            max_attempts=1,
        )
        self.assignment = factories.assign_variant(
            template=self.template, username=self.user.username
        )

    def test_full_variant_flow(self):
        current_resp = self.client.get("/api/variants/assignments/current/")
        self.assertEqual(current_resp.status_code, 200)
        current_data = current_resp.json()
        self.assertEqual(len(current_data), 1)
        assignment_payload = current_data[0]
        self.assertEqual(assignment_payload["id"], self.assignment.id)
        self.assertIsNone(assignment_payload["active_attempt"])
        self.assertEqual(assignment_payload["attempts_left"], 2)
        self.assertEqual(assignment_payload["progress"]["solved_tasks"], 0)

        start_resp = self.client.post(
            f"/api/variants/assignments/{self.assignment.id}/attempts/start/"
        )
        self.assertEqual(start_resp.status_code, 201)
        attempt_payload = start_resp.json()
        self.assertEqual(attempt_payload["attempt_number"], 1)
        self.assertIsNone(attempt_payload["completed_at"])
        self.assertIsNotNone(attempt_payload["time_limit"])
        attempt_id = attempt_payload["id"]

        # Assignment should now expose the active attempt
        current_resp = self.client.get("/api/variants/assignments/current/")
        assignment_payload = current_resp.json()[0]
        self.assertIsNotNone(assignment_payload["active_attempt"])
        self.assertEqual(assignment_payload["attempts_left"], 1)

        incorrect_payload = {
            "is_correct": False,
            "task_snapshot": {"question": "Q1", "chosen": "A"},
        }
        submit_resp = self.client.post(
            f"/api/variants/attempts/{attempt_id}/tasks/{self.variant_task_1.id}/submit/",
            data=json.dumps(incorrect_payload),
            content_type="application/json",
        )
        self.assertEqual(submit_resp.status_code, 201)
        progress_payload = submit_resp.json()["tasks_progress"]
        first_task_entry = next(
            item for item in progress_payload if item["variant_task_id"] == self.variant_task_1.id
        )
        self.assertEqual(first_task_entry["attempts_used"], 1)
        self.assertFalse(first_task_entry["is_completed"])
        self.assertIsNotNone(first_task_entry["task_snapshot"])
        first_attempt_snapshot = first_task_entry["attempts"][0]["task_snapshot"]
        self.assertEqual(
            first_attempt_snapshot["response"], incorrect_payload["task_snapshot"]
        )
        self.assertEqual(
            first_attempt_snapshot["task"], first_task_entry["task_snapshot"]
        )

        correct_payload = {
            "is_correct": True,
            "task_snapshot": {"question": "Q1", "chosen": "B"},
        }
        submit_resp = self.client.post(
            f"/api/variants/attempts/{attempt_id}/tasks/{self.variant_task_1.id}/submit/",
            data=json.dumps(correct_payload),
            content_type="application/json",
        )
        self.assertEqual(submit_resp.status_code, 201)
        first_task_entry = next(
            item for item in submit_resp.json()["tasks_progress"]
            if item["variant_task_id"] == self.variant_task_1.id
        )
        self.assertEqual(first_task_entry["attempts_used"], 2)
        self.assertTrue(first_task_entry["is_completed"])

        second_payload = {"is_correct": True, "task_snapshot": {"question": "Q2"}}
        submit_resp = self.client.post(
            f"/api/variants/attempts/{attempt_id}/tasks/{self.variant_task_2.id}/submit/",
            data=json.dumps(second_payload),
            content_type="application/json",
        )
        self.assertEqual(submit_resp.status_code, 201)
        second_task_entry = next(
            item for item in submit_resp.json()["tasks_progress"]
            if item["variant_task_id"] == self.variant_task_2.id
        )
        self.assertTrue(second_task_entry["is_completed"])
        self.assertEqual(second_task_entry["attempts_used"], 1)

        finalize_resp = self.client.post(f"/api/variants/attempts/{attempt_id}/finalize/")
        self.assertEqual(finalize_resp.status_code, 200)
        self.assertIsNotNone(finalize_resp.json()["completed_at"])

        current_resp = self.client.get("/api/variants/assignments/current/")
        assignment_payload = current_resp.json()[0]
        self.assertIsNone(assignment_payload["active_attempt"])
        self.assertEqual(assignment_payload["progress"]["solved_tasks"], 2)
        self.assertEqual(assignment_payload["attempts_left"], 1)

        second_start = self.client.post(
            f"/api/variants/assignments/{self.assignment.id}/attempts/start/"
        )
        self.assertEqual(second_start.status_code, 201)
        second_attempt_id = second_start.json()["id"]
        second_attempt = VariantAttempt.objects.get(pk=second_attempt_id)

        with mock.patch("apps.recsys.service_utils.variants.timezone.now") as mocked_now:
            mocked_now.return_value = (
                second_attempt.started_at
                + self.template.time_limit
                + timedelta(minutes=1)
            )
            timeout_resp = self.client.post(
                f"/api/variants/attempts/{second_attempt_id}/tasks/{self.variant_task_2.id}/submit/",
                data=json.dumps({"is_correct": False}),
                content_type="application/json",
            )
        self.assertEqual(timeout_resp.status_code, 400)

        finalize_resp = self.client.post(
            f"/api/variants/attempts/{second_attempt_id}/finalize/"
        )
        self.assertEqual(finalize_resp.status_code, 200)

        current_resp = self.client.get("/api/variants/assignments/current/")
        self.assertEqual(current_resp.json(), [])

        past_resp = self.client.get("/api/variants/assignments/past/")
        self.assertEqual(past_resp.status_code, 200)
        self.assertEqual(len(past_resp.json()), 1)

        third_start = self.client.post(
            f"/api/variants/assignments/{self.assignment.id}/attempts/start/"
        )
        self.assertEqual(third_start.status_code, 400)

        history_resp = self.client.get(
            f"/api/variants/assignments/{self.assignment.id}/history/"
        )
        self.assertEqual(history_resp.status_code, 200)
        history_payload = history_resp.json()
        self.assertEqual(history_payload["id"], self.assignment.id)
        self.assertEqual(len(history_payload["attempts"]), 2)
        first_attempt_history = history_payload["attempts"][0]
        first_task_progress = next(
            item
            for item in first_attempt_history["tasks_progress"]
            if item["variant_task_id"] == self.variant_task_1.id
        )
        self.assertTrue(first_task_progress["is_completed"])
        self.assertEqual(len(first_task_progress["attempts"]), 2)
        self.assertEqual(
            first_task_progress["attempts"][0]["task_snapshot"]["response"],
            incorrect_payload["task_snapshot"],
        )
