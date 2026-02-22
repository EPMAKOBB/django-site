from __future__ import annotations

from django.test import TestCase

from apps.recsys.models import Task, VariantTaskAttempt
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


class InformaticsPathCounterGeneratorTests(TestCase):
    def test_generator_produces_consistent_positive_paths(self):
        task = factories.create_task(
            is_dynamic=True,
            generator_slug="informatics/path-counter",
            default_payload={},
        )

        payload_one: dict[str, object] = {}
        payload_two: dict[str, object] = {}

        first = task_generation.generate(task, payload_one, seed=2024, student=None)
        second = task_generation.generate(task, payload_two, seed=2024, student=None)

        self.assertEqual(first.content, second.content)
        self.assertEqual(first.answers, second.answers)
        self.assertEqual(first.payload, second.payload)
        self.assertEqual(first.meta, second.meta)

        self.assertIn("paths", first.answers)
        self.assertGreater(first.answers["paths"], 0)

        commands = first.payload["commands"]
        self.assertIsInstance(commands, list)
        self.assertGreaterEqual(len(commands), 2)

        required_index = first.payload["required_command_index"]
        forbidden_index = first.payload["forbidden_command_index"]
        if required_index is not None:
            self.assertTrue(0 <= required_index < len(commands))
        if forbidden_index is not None:
            self.assertTrue(0 <= forbidden_index < len(commands))

        self.assertLessEqual(first.meta["max_depth"], 7)
        self.assertLessEqual(first.meta["state_count"], 120)
        self.assertLessEqual(first.meta["max_width"], 40)
        self.assertLessEqual(first.meta["depth_reached"], first.meta["max_depth"])

        transitions = first.payload["transitions"]
        self.assertIsInstance(transitions, dict)
        for value, edges in transitions.items():
            self.assertIsInstance(value, int)
            self.assertIsInstance(edges, list)
            for edge in edges:
                self.assertIn("command", edge)
                self.assertIn("result", edge)


class VariantGenerationTests(TestCase):
    def setUp(self):
        self.template = factories.create_variant_template()
        self.static_task = factories.create_task(
            title="Static",
            default_payload={"answers": ["A"]},
            difficulty_level=25,
            correct_answer={"value": "A"},
        )
        self.dynamic_task = factories.create_task(
            subject=self.static_task.subject,
            title="Dynamic",
            is_dynamic=True,
            generator_slug="math/addition",
            default_payload={"min": 2, "max": 5},
            difficulty_level=80,
            correct_answer={"formula": "a + b"},
        )
        self.pre_generated_task = factories.create_task(
            subject=self.static_task.subject,
            title="Pre-generated",
            is_dynamic=True,
            dynamic_mode=Task.DynamicMode.PRE_GENERATED,
            description=(
                "Сколько существует {base_name} {length}-значных чисел, "
                "содержащих ровно одну цифру {target}?"
            ),
            default_payload={"base_name": "семеричных", "length": 5, "target": 6},
            difficulty_level=60,
            correct_answer={"value": 0},
        )
        self.pre_generated_datasets = [
            factories.add_pre_generated_dataset(
                task=self.pre_generated_task,
                parameter_values={
                    "base_name": "четырнадцатеричных",
                    "length": 4,
                    "target": 3,
                },
                correct_answer={"value": 7344},
            ),
            factories.add_pre_generated_dataset(
                task=self.pre_generated_task,
                parameter_values={
                    "base_name": "тринадцатеричных",
                    "length": 4,
                    "target": 0,
                },
                correct_answer={"value": 4620},
            ),
        ]
        self.static_variant_task = factories.add_variant_task(
            template=self.template, task=self.static_task, order=1
        )
        self.dynamic_variant_task = factories.add_variant_task(
            template=self.template, task=self.dynamic_task, order=2
        )
        self.pre_generated_variant_task = factories.add_variant_task(
            template=self.template, task=self.pre_generated_task, order=3
        )
        self.assignment = factories.assign_variant(template=self.template)

    def test_snapshots_created_during_start(self):
        attempt = variant_service.start_new_attempt(
            self.assignment.user, self.assignment.id
        )

        generation_attempts = VariantTaskAttempt.objects.filter(
            variant_attempt=attempt, attempt_number=0
        )
        self.assertEqual(generation_attempts.count(), 3)

        static_snapshot = generation_attempts.get(
            variant_task=self.static_variant_task
        ).task_snapshot["task"]
        dynamic_snapshot = generation_attempts.get(
            variant_task=self.dynamic_variant_task
        ).task_snapshot["task"]
        pre_generated_snapshot = generation_attempts.get(
            variant_task=self.pre_generated_variant_task
        ).task_snapshot["task"]

        self.assertEqual(static_snapshot["type"], "static")
        self.assertEqual(static_snapshot["title"], self.static_task.title)
        self.assertEqual(static_snapshot["difficulty_level"], 25)
        self.assertEqual(static_snapshot["correct_answer"], {"value": "A"})
        self.assertIsNone(static_snapshot["image"])
        self.assertEqual(dynamic_snapshot["type"], "dynamic")
        self.assertEqual(dynamic_snapshot["generator_slug"], "math/addition")
        self.assertIn("content", dynamic_snapshot)
        self.assertEqual(dynamic_snapshot["difficulty_level"], 80)
        self.assertEqual(dynamic_snapshot["correct_answer"], {"formula": "a + b"})
        self.assertEqual(pre_generated_snapshot["type"], "dynamic")
        self.assertEqual(
            pre_generated_snapshot["generation_mode"],
            Task.DynamicMode.PRE_GENERATED,
        )
        dataset_ids = [item.id for item in self.pre_generated_datasets]
        self.assertIn(pre_generated_snapshot["dataset_id"], dataset_ids)
        selected_dataset = next(
            item
            for item in self.pre_generated_datasets
            if item.id == pre_generated_snapshot["dataset_id"]
        )
        self.assertEqual(
            pre_generated_snapshot["payload"], selected_dataset.parameter_values
        )
        self.assertEqual(
            pre_generated_snapshot["correct_answer"], selected_dataset.correct_answer
        )
        self.assertIn(
            str(selected_dataset.parameter_values["target"]),
            pre_generated_snapshot["content"]["statement"],
        )
        self.assertEqual(
            pre_generated_snapshot["difficulty_level"],
            self.pre_generated_task.difficulty_level,
        )

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
        pre_generated_entry = next(
            item
            for item in progress
            if item["variant_task_id"] == self.pre_generated_variant_task.id
        )

        self.assertEqual(static_entry["task_snapshot"], static_snapshot)
        self.assertEqual(dynamic_entry["task_snapshot"], dynamic_snapshot)
        self.assertEqual(pre_generated_entry["task_snapshot"], pre_generated_snapshot)

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
        self.assertEqual(attempt_snapshot["task"]["difficulty_level"], 80)
        self.assertEqual(attempt_snapshot["task"]["correct_answer"], {"formula": "a + b"})

    def test_pre_generated_dataset_selection_is_seed_based(self):
        first = self.pre_generated_task.pick_pregenerated_dataset(seed=10)
        second = self.pre_generated_task.pick_pregenerated_dataset(seed=10)
        alternate = self.pre_generated_task.pick_pregenerated_dataset(seed=11)

        self.assertEqual(first.id, second.id)
        self.assertIn(alternate.id, [item.id for item in self.pre_generated_datasets])

    def test_pre_generated_snapshot_is_captured_on_submission(self):
        attempt = variant_service.start_new_attempt(
            self.assignment.user, self.assignment.id
        )

        variant_service.submit_task_answer(
            self.assignment.user,
            attempt.id,
            self.pre_generated_variant_task.id,
            is_correct=True,
        )

        attempt = variant_service.get_attempt_with_prefetch(
            self.assignment.user, attempt.id
        )
        progress = variant_service.build_tasks_progress(attempt)
        entry = next(
            item
            for item in progress
            if item["variant_task_id"] == self.pre_generated_variant_task.id
        )
        self.assertEqual(entry["attempts_used"], 1)
        stored_snapshot = entry["attempts"][0].task_snapshot["task"]

        self.assertEqual(
            stored_snapshot["dataset_id"], entry["task_snapshot"]["dataset_id"]
        )
        self.assertEqual(
            stored_snapshot["generation_mode"],
            Task.DynamicMode.PRE_GENERATED,
        )
        self.assertEqual(
            stored_snapshot["payload"], entry["task_snapshot"]["payload"]
        )

    def test_submit_task_answer_without_generated_snapshot_includes_metadata(self):
        attempt = variant_service.start_new_attempt(
            self.assignment.user, self.assignment.id
        )

        response = variant_service.submit_task_answer(
            self.assignment.user,
            attempt.id,
            self.static_variant_task.id,
            is_correct=True,
        )

        snapshot = response.task_attempt.task_snapshot["task"]
        self.assertEqual(snapshot["type"], "static")
        self.assertEqual(snapshot["difficulty_level"], 25)
        self.assertEqual(snapshot["correct_answer"], {"value": "A"})
        self.assertIn("rendering_strategy", snapshot)

    def test_save_task_response_overwrites_previous_value(self):
        attempt = variant_service.start_new_attempt(
            self.assignment.user, self.assignment.id
        )

        first_answer = {"value": "B"}
        variant_service.save_task_response(
            self.assignment.user,
            attempt.id,
            self.static_variant_task.id,
            answer=first_answer,
        )

        attempt = variant_service.get_attempt_with_prefetch(
            self.assignment.user, attempt.id
        )
        progress = variant_service.build_tasks_progress(attempt)
        entry = next(
            item for item in progress if item["variant_task_id"] == self.static_variant_task.id
        )
        self.assertEqual(entry["saved_response"], first_answer)
        self.assertIsNotNone(entry["saved_response_updated_at"])
        self.assertEqual(entry["attempts_used"], 0)

        generation_attempt = attempt.task_attempts.get(
            variant_task=self.static_variant_task,
            attempt_number=0,
        )
        self.assertEqual(
            generation_attempt.task_snapshot["response"]["value"],
            first_answer,
        )

        second_answer = {"value": "C"}
        variant_service.save_task_response(
            self.assignment.user,
            attempt.id,
            self.static_variant_task.id,
            answer=second_answer,
        )

        attempt = variant_service.get_attempt_with_prefetch(
            self.assignment.user, attempt.id
        )
        progress = variant_service.build_tasks_progress(attempt)
        entry = next(
            item for item in progress if item["variant_task_id"] == self.static_variant_task.id
        )
        self.assertEqual(entry["saved_response"], second_answer)

        generation_attempt.refresh_from_db()
        self.assertEqual(
            generation_attempt.task_snapshot["response"]["value"],
            second_answer,
        )

    def test_finalize_attempt_evaluates_saved_responses(self):
        attempt = variant_service.start_new_attempt(
            self.assignment.user, self.assignment.id
        )

        variant_service.save_task_response(
            self.assignment.user,
            attempt.id,
            self.static_variant_task.id,
            answer={"value": "A"},
        )
        variant_service.save_task_response(
            self.assignment.user,
            attempt.id,
            self.dynamic_variant_task.id,
            answer={"formula": "a + c"},
        )

        variant_service.finalize_attempt(self.assignment.user, attempt.id)

        attempt = variant_service.get_attempt_with_prefetch(
            self.assignment.user, attempt.id
        )
        self.assertIsNotNone(attempt.completed_at)

        progress = variant_service.build_tasks_progress(attempt)
        static_entry = next(
            item for item in progress if item["variant_task_id"] == self.static_variant_task.id
        )
        dynamic_entry = next(
            item for item in progress if item["variant_task_id"] == self.dynamic_variant_task.id
        )

        self.assertTrue(static_entry["is_completed"])
        self.assertFalse(dynamic_entry["is_completed"])
        self.assertEqual(static_entry["attempts_used"], 1)
        self.assertEqual(dynamic_entry["attempts_used"], 1)

        static_attempt = static_entry["attempts"][0]
        dynamic_attempt = dynamic_entry["attempts"][0]

        self.assertTrue(static_attempt.is_correct)
        self.assertEqual(
            static_attempt.task_snapshot["response"]["value"],
            {"value": "A"},
        )
        self.assertFalse(dynamic_attempt.is_correct)
        self.assertEqual(
            dynamic_attempt.task_snapshot["response"]["value"],
            {"formula": "a + c"},
        )

        self.assignment.refresh_from_db()
        progress_summary = variant_service.calculate_assignment_progress(self.assignment)
        self.assertEqual(progress_summary["solved_tasks"], 1)

    def test_task_body_html_falls_back_to_task_description_without_generation_snapshot(self):
        self.static_task.description = "first line\nsecond line"
        self.static_task.rendering_strategy = Task.RenderingStrategy.PLAIN
        self.static_task.save(update_fields=["description", "rendering_strategy"])

        attempt = variant_service.start_new_attempt(
            self.assignment.user, self.assignment.id
        )
        VariantTaskAttempt.objects.filter(
            variant_attempt=attempt,
            variant_task=self.static_variant_task,
            attempt_number=0,
        ).delete()

        attempt = variant_service.get_attempt_with_prefetch(
            self.assignment.user, attempt.id
        )
        progress = variant_service.build_tasks_progress(attempt)
        entry = next(
            item for item in progress if item["variant_task_id"] == self.static_variant_task.id
        )

        self.assertIsNone(entry["task_snapshot"])
        self.assertIn("first line", entry["task_body_html"])
        self.assertIn("second line", entry["task_body_html"])
        self.assertIn("<br>", entry["task_body_html"])

    def test_task_body_html_prefers_snapshot_description_over_task_description(self):
        self.static_task.description = "Task description fallback"
        self.static_task.rendering_strategy = Task.RenderingStrategy.PLAIN
        self.static_task.save(update_fields=["description", "rendering_strategy"])

        attempt = variant_service.start_new_attempt(
            self.assignment.user, self.assignment.id
        )
        generation_attempt = VariantTaskAttempt.objects.get(
            variant_attempt=attempt,
            variant_task=self.static_variant_task,
            attempt_number=0,
        )
        generation_attempt.task_snapshot["task"]["description"] = "Snapshot **bold**"
        generation_attempt.task_snapshot["task"]["rendering_strategy"] = (
            Task.RenderingStrategy.MARKDOWN
        )
        generation_attempt.save(update_fields=["task_snapshot"])

        attempt = variant_service.get_attempt_with_prefetch(
            self.assignment.user, attempt.id
        )
        progress = variant_service.build_tasks_progress(attempt)
        entry = next(
            item for item in progress if item["variant_task_id"] == self.static_variant_task.id
        )

        self.assertIn("<strong>bold</strong>", entry["task_body_html"])
        self.assertNotIn("Task description fallback", entry["task_body_html"])
