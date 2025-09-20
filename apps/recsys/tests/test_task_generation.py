from __future__ import annotations

from django.test import TestCase

from apps.recsys.models import VariantTaskAttempt
from apps.recsys.service_utils import task_generation, variants as variant_service

from . import factories


class TaskGenerationRegistryTests(TestCase):
    def test_generator_is_deterministic_by_seed(self):
        task = factories.create_task(
            is_dynamic=True,
            generator_slug="math/addition",
            default_payload={"min": 1, "max": 3},
        )

        payload_one = {"min": 1, "max": 3}
        payload_two = {"min": 1, "max": 3}

        first = task_generation.generate(task, payload_one, seed=42, student=None)
        second = task_generation.generate(task, payload_two, seed=42, student=None)

        self.assertEqual(first.content, second.content)
        self.assertEqual(first.answers, second.answers)
        self.assertEqual(first.payload, second.payload)


class VariantGenerationTests(TestCase):
    def setUp(self):
        self.template = factories.create_variant_template()
        self.static_task = factories.create_task(
            title="Static",
            default_payload={"answers": ["A"]},
        )
        self.dynamic_task = factories.create_task(
            subject=self.static_task.subject,
            title="Dynamic",
            is_dynamic=True,
            generator_slug="math/addition",
            default_payload={"min": 2, "max": 5},
        )
        self.static_variant_task = factories.add_variant_task(
            template=self.template, task=self.static_task, order=1
        )
        self.dynamic_variant_task = factories.add_variant_task(
            template=self.template, task=self.dynamic_task, order=2
        )
        self.assignment = factories.assign_variant(template=self.template)

    def test_snapshots_created_during_start(self):
        attempt = variant_service.start_new_attempt(
            self.assignment.user, self.assignment.id
        )

        generation_attempts = VariantTaskAttempt.objects.filter(
            variant_attempt=attempt, attempt_number=0
        )
        self.assertEqual(generation_attempts.count(), 2)

        static_snapshot = generation_attempts.get(
            variant_task=self.static_variant_task
        ).task_snapshot["task"]
        dynamic_snapshot = generation_attempts.get(
            variant_task=self.dynamic_variant_task
        ).task_snapshot["task"]

        self.assertEqual(static_snapshot["type"], "static")
        self.assertEqual(static_snapshot["title"], self.static_task.title)
        self.assertEqual(dynamic_snapshot["type"], "dynamic")
        self.assertEqual(dynamic_snapshot["generator_slug"], "math/addition")
        self.assertIn("content", dynamic_snapshot)

        attempt = variant_service.get_attempt_with_prefetch(
            self.assignment.user, attempt.id
        )
        progress = variant_service.build_tasks_progress(attempt)
        static_entry = next(
            item for item in progress if item["variant_task_id"] == self.static_variant_task.id
        )
        dynamic_entry = next(
            item for item in progress if item["variant_task_id"] == self.dynamic_variant_task.id
        )

        self.assertEqual(static_entry["task_snapshot"], static_snapshot)
        self.assertEqual(dynamic_entry["task_snapshot"], dynamic_snapshot)

    def test_snapshot_is_used_when_submitting_answer(self):
        attempt = variant_service.start_new_attempt(
            self.assignment.user, self.assignment.id
        )

        response_payload = {"answer": "42"}
        variant_service.submit_task_answer(
            self.assignment.user,
            attempt.id,
            self.dynamic_variant_task.id,
            is_correct=False,
            task_snapshot=response_payload,
        )

        attempt = variant_service.get_attempt_with_prefetch(
            self.assignment.user, attempt.id
        )
        progress = variant_service.build_tasks_progress(attempt)
        entry = next(
            item for item in progress if item["variant_task_id"] == self.dynamic_variant_task.id
        )
        self.assertEqual(entry["attempts_used"], 1)
        attempt_snapshot = entry["attempts"][0].task_snapshot
        self.assertEqual(attempt_snapshot["response"], response_payload)
        self.assertEqual(attempt_snapshot["task"], entry["task_snapshot"])
