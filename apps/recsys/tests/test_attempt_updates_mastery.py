import json
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.recsys.models import (
    ExamVersion,
    Skill,
    Subject,
    TaskType,
    Task,
    TaskSkill,
    SkillMastery,
)


class AttemptUpdatesMasteryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="user")
        self.client.force_login(self.user)
        subject = Subject.objects.create(name="Math")
        exam_version = ExamVersion.objects.create(
            subject=subject, exam_type="EGE", year=2024, label="EGE 2024"
        )
        self.skill = Skill.objects.create(name="S1", exam_version=exam_version)
        self.task_type = TaskType.objects.create(name="T1", exam_version=exam_version)
        self.task = Task.objects.create(type=self.task_type, title="Task")
        TaskSkill.objects.create(task=self.task, skill=self.skill, weight=1.0)

    def test_mastery_and_confidence_increase(self):
        payload = {"user": self.user.id, "task": self.task.id, "is_correct": True}
        self.client.post("/api/attempts/", data=json.dumps(payload), content_type="application/json")
        sm = SkillMastery.objects.get(user=self.user, skill=self.skill)
        self.assertEqual(sm.mastery, 1.0)
