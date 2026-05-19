import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.recsys.models import (
    Attempt,
    Subject,
    ExamVersion,
    Skill,
    TagMastery,
    TaskType,
    Task,
    TaskTag,
    TaskSkill,
    SkillMastery,
    TypeMastery,
)
from apps.recsys.tests import factories


class AttemptUpdatesMasteryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="user")
        self.client.force_login(self.user)
        self.subject = Subject.objects.create(name="Subject")
        self.exam_version = ExamVersion.objects.create(name="V1", subject=self.subject)
        self.skill = Skill.objects.create(name="S1", subject=self.subject)
        self.tag = TaskTag.objects.create(name="Tag1", subject=self.subject)
        self.task_type = TaskType.objects.create(name="T1", subject=self.subject)
        self.task = Task.objects.create(
            type=self.task_type,
            title="Task",
            subject=self.subject,
            exam_version=self.exam_version,
            level_band=Task.LevelBand.EXAM,
            expected_time_seconds=60,
            max_score=2,
            status=Task.Status.PUBLISHED,
        )
        self.task.tags.add(self.tag)
        TaskSkill.objects.create(task=self.task, skill=self.skill, weight=1.0)

    def test_mastery_and_confidence_increase(self):
        payload = {"user": self.user.id, "task": self.task.id, "is_correct": True}
        response = self.client.post(
            "/api/attempts/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)

        attempt = Attempt.objects.get()
        self.assertEqual(attempt.attempts_count, 1)
        self.assertEqual(attempt.weight, 1.0)

        sm = SkillMastery.objects.get(user=self.user, skill=self.skill)
        self.assertEqual(sm.mastery, 0.2)
        self.assertEqual(sm.confidence, 0.0)
        self.assertEqual(self.task.subject, self.subject)
        self.assertEqual(self.task.exam_version, self.exam_version)

    def test_repeated_attempts_reduce_weight(self):
        first_payload = {"user": self.user.id, "task": self.task.id, "is_correct": False}
        second_payload = {"user": self.user.id, "task": self.task.id, "is_correct": True}

        self.client.post(
            "/api/attempts/",
            data=json.dumps(first_payload),
            content_type="application/json",
        )
        self.client.post(
            "/api/attempts/",
            data=json.dumps(second_payload),
            content_type="application/json",
        )

        attempts = Attempt.objects.order_by("created_at")
        self.assertEqual(attempts.count(), 2)
        self.assertEqual(attempts[0].weight, 1.0)
        self.assertEqual(attempts[1].weight, 0.5)

        mastery = SkillMastery.objects.get(user=self.user, skill=self.skill)
        self.assertEqual(mastery.mastery, 0.1)

    def test_updates_tag_mastery_and_task_aggregates(self):
        checked_at = timezone.now()
        Attempt.objects.create(
            user=self.user,
            task=self.task,
            is_correct=False,
            score=1,
            max_score=2,
            time_spent=timedelta(seconds=60),
            checked_at=checked_at,
        )

        tag_mastery = TagMastery.objects.get(user=self.user, task_tag=self.tag)
        self.assertAlmostEqual(tag_mastery.mastery, 0.075)
        self.assertAlmostEqual(tag_mastery.coverage, 0.04)
        self.assertAlmostEqual(tag_mastery.progress, 0.05)
        self.assertAlmostEqual(tag_mastery.confidence, 1 - 2.718281828459045 ** (-1 / 5), places=5)
        self.assertEqual(tag_mastery.stability, 0.0)
        self.assertEqual(tag_mastery.attempts_total, 1)
        self.assertEqual(tag_mastery.successes_total, 0)
        self.assertEqual(tag_mastery.last_seen_at, checked_at)
        self.assertIsNone(tag_mastery.last_success_at)

        self.task.refresh_from_db()
        self.assertEqual(self.task.attempts_total, 1)
        self.assertAlmostEqual(self.task.score_norm_sum_total, 0.5)
        self.assertAlmostEqual(self.task.difficulty_empirical, 0.5)
        self.assertEqual(self.task.first_attempt_total, 1)
        self.assertEqual(self.task.first_attempt_failed, 1)
        self.assertEqual(self.task.time_spent_count, 1)
        self.assertAlmostEqual(self.task.time_spent_sum_seconds, 60.0)
        self.assertAlmostEqual(self.task.time_spent_avg_seconds, 60.0)

        type_mastery = TypeMastery.objects.get(user=self.user, task_type=self.task_type)
        self.assertAlmostEqual(type_mastery.mastery, 0.075)
        self.assertAlmostEqual(type_mastery.coverage, 0.04)
        self.assertAlmostEqual(type_mastery.progress, 0.05)
        self.assertEqual(type_mastery.attempts_total, 1)
        self.assertEqual(type_mastery.successes_total, 0)

    def test_time_aggregate_ignores_suspiciously_long_attempt_time(self):
        Attempt.objects.create(
            user=self.user,
            task=self.task,
            is_correct=True,
            score=2,
            max_score=2,
            time_spent=timedelta(seconds=self.task.expected_time_seconds * 10),
        )

        self.task.refresh_from_db()
        self.assertEqual(self.task.attempts_total, 1)
        self.assertEqual(self.task.time_spent_count, 0)
        self.assertEqual(self.task.time_spent_sum_seconds, 0.0)
        self.assertIsNone(self.task.time_spent_avg_seconds)

    def test_variant_task_attempt_scoped_aggregation(self):
        template = factories.create_variant_template()
        variant_task = factories.add_variant_task(template=template, task=self.task)
        assignment = factories.assign_variant(template=template, username=self.user.username)
        variant_attempt = factories.start_attempt(assignment=assignment)
        task_attempt = factories.add_task_attempt(
            variant_attempt=variant_attempt,
            variant_task=variant_task,
            attempt_number=1,
            is_correct=False,
        )

        Attempt.objects.create(
            user=self.user,
            task=self.task,
            is_correct=False,
            variant_task_attempt=task_attempt,
        )
        Attempt.objects.create(
            user=self.user,
            task=self.task,
            is_correct=True,
            variant_task_attempt=task_attempt,
        )

        attempts = Attempt.objects.filter(variant_task_attempt=task_attempt).order_by(
            "created_at"
        )
        self.assertEqual(attempts.count(), 2)
        self.assertEqual(attempts[0].attempts_count, 1)
        self.assertEqual(attempts[0].weight, 1.0)
        self.assertEqual(attempts[1].attempts_count, 2)
        self.assertEqual(attempts[1].weight, 0.5)

        mastery = SkillMastery.objects.get(user=self.user, skill=self.skill)
        self.assertEqual(mastery.mastery, 0.1)
