import json
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.recsys.models import (
    Subject,
    ExamVersion,
    Skill,
    TaskType,
    Task,
    TaskSkill,
    SkillMastery,
)


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
        self.client.post("/api/attempts/", data=json.dumps(payload), content_type="application/json")
        sm = SkillMastery.objects.get(user=self.user, skill=self.skill)
        self.assertEqual(sm.mastery, 1.0)
        self.assertEqual(sm.confidence, 0.0)
        self.assertEqual(self.task.subject, self.subject)
        self.assertEqual(self.task.exam_version, self.exam_version)
