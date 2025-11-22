import json
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.recsys.models import (
    Attempt,
    Subject,
    ExamVersion,
    Skill,
    TaskType,
    Task,
    TaskSkill,
    SkillMastery,
)
from apps.recsys.tests import factories


class AttemptUpdatesMasteryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="user")
        self.client.force_login(self.user)
        self.subject = Subject.objects.create(name="Subject")
        self.exam_version = ExamVersion.objects.create(name="V1", subject=self.subject)
        self.skill = Skill.objects.create(name="S1", subject=self.subject)
        self.task_type = TaskType.objects.create(name="T1", subject=self.subject)
        self.task = Task.objects.create(
            type=self.task_type,
            title="Task",
            subject=self.subject,
            exam_version=self.exam_version,
        )
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
