from datetime import timedelta

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from apps.recsys.models import (
    VariantAssignment,
    VariantAttempt,
    VariantTask,
    VariantTaskAttempt,
)
from . import factories


class VariantTaskModelTests(TestCase):
    def test_variant_task_order_unique_per_template(self):
        template = factories.create_variant_template()
        first_task = factories.create_task()
        second_task = factories.create_task(subject=first_task.subject)
        factories.add_variant_task(template=template, task=first_task, order=1)

        with self.assertRaises(IntegrityError):
            factories.add_variant_task(template=template, task=second_task, order=1)

    def test_variant_task_unique_task_per_template(self):
        template = factories.create_variant_template()
        task = factories.create_task()
        factories.add_variant_task(template=template, task=task, order=1)

        with self.assertRaises(IntegrityError):
            factories.add_variant_task(template=template, task=task, order=2)

    def test_variant_task_cascade_on_template_delete(self):
        template = factories.create_variant_template()
        task = factories.create_task()
        variant_task = factories.add_variant_task(template=template, task=task, order=1)
        self.assertEqual(VariantTask.objects.count(), 1)

        template.delete()
        self.assertEqual(VariantTask.objects.count(), 0)
        self.assertFalse(VariantTask.objects.filter(pk=variant_task.pk).exists())


class VariantAssignmentModelTests(TestCase):
    def test_variant_assignment_cascade_on_template_delete(self):
        template = factories.create_variant_template()
        assignment = factories.assign_variant(template=template)
        self.assertEqual(VariantAssignment.objects.count(), 1)

        template.delete()
        self.assertEqual(VariantAssignment.objects.count(), 0)

    def test_variant_assignment_cascade_attempts(self):
        template = factories.create_variant_template()
        assignment = factories.assign_variant(template=template)
        attempt = factories.start_attempt(assignment=assignment)
        assignment_id = assignment.pk
        attempt_id = attempt.pk
        self.assertEqual(assignment.attempts.count(), 1)

        assignment.delete()
        self.assertFalse(VariantAssignment.objects.filter(pk=assignment_id).exists())
        self.assertFalse(VariantAttempt.objects.filter(pk=attempt_id).exists())

    def test_mark_started_sets_timestamp(self):
        template = factories.create_variant_template()
        assignment = factories.assign_variant(template=template)
        self.assertIsNone(assignment.started_at)

        assignment.mark_started()
        self.assertIsNotNone(assignment.started_at)

    def test_deadline_stored(self):
        template = factories.create_variant_template()
        deadline = timezone.now() + timedelta(days=1)
        assignment = factories.assign_variant(template=template, deadline=deadline)
        self.assertEqual(assignment.deadline, deadline)


class VariantAttemptModelTests(TestCase):
    def _create_attempt_with_task(self):
        template = factories.create_variant_template()
        task = factories.create_task()
        variant_task = factories.add_variant_task(template=template, task=task, order=1)
        assignment = factories.assign_variant(template=template)
        attempt = factories.start_attempt(assignment=assignment)
        return attempt, variant_task

    def test_attempt_cascade_task_attempts(self):
        attempt, variant_task = self._create_attempt_with_task()
        task_attempt = factories.add_task_attempt(
            variant_attempt=attempt,
            variant_task=variant_task,
        )
        attempt_id = attempt.pk
        self.assertEqual(
            attempt.task_attempts.filter(attempt_number__gt=0).count(),
            1,
        )

        attempt.delete()
        self.assertEqual(VariantTaskAttempt.objects.count(), 0)
        self.assertFalse(VariantTaskAttempt.objects.filter(pk=task_attempt.pk).exists())
        self.assertFalse(VariantAttempt.objects.filter(pk=attempt_id).exists())

    def test_mark_completed_sets_fields(self):
        attempt, _ = self._create_attempt_with_task()
        self.assertIsNone(attempt.completed_at)
        self.assertIsNone(attempt.time_spent)

        attempt.mark_completed()
        attempt.refresh_from_db()
        self.assertIsNotNone(attempt.completed_at)
        self.assertIsNotNone(attempt.time_spent)

    def test_task_attempt_unique_constraint(self):
        attempt, variant_task = self._create_attempt_with_task()
        factories.add_task_attempt(
            variant_attempt=attempt,
            variant_task=variant_task,
            attempt_number=1,
        )

        with self.assertRaises(IntegrityError):
            factories.add_task_attempt(
                variant_attempt=attempt,
                variant_task=variant_task,
                attempt_number=1,
            )

    def test_task_snapshot_persisted(self):
        attempt, variant_task = self._create_attempt_with_task()
        snapshot = {
            "task": {
                "type": "dynamic",
                "title": "custom",
                "payload": {"difficulty": "hard"},
            },
            "response": {"answer": "42"},
        }
        task_attempt = factories.add_task_attempt(
            variant_attempt=attempt,
            variant_task=variant_task,
            attempt_number=1,
            task_snapshot=snapshot,
            is_correct=True,
        )
        self.assertEqual(task_attempt.task_snapshot, snapshot)
        self.assertTrue(task_attempt.is_correct)
