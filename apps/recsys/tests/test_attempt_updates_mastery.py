import json
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.recsys.models import Skill, TaskType, Task, TaskSkill, SkillMastery


class AttemptUpdatesMasteryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="user")
        self.skill = Skill.objects.create(name="S1")
        self.task_type = TaskType.objects.create(name="T1")
        self.task = Task.objects.create(type=self.task_type, title="Task")
        TaskSkill.objects.create(task=self.task, skill=self.skill, weight=1.0)

    def test_mastery_and_confidence_increase(self):
        payload = {"user": self.user.id, "task": self.task.id, "is_correct": True}
        self.client.post("/api/attempts/", data=json.dumps(payload), content_type="application/json")
        sm = SkillMastery.objects.get(user=self.user, skill=self.skill)
        self.assertEqual(sm.mastery, 1.0)
        self.assertEqual(sm.confidence, 1.0)
