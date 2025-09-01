import json
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.recsys.models import Skill, TaskType, Task, TaskSkill


class ApiContractsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="user")
        self.skill = Skill.objects.create(name="Skill")
        self.ttype = TaskType.objects.create(name="Type")
        self.task = Task.objects.create(type=self.ttype, title="Task")
        TaskSkill.objects.create(task=self.task, skill=self.skill, weight=1.0)

    def test_endpoints(self):
        # next task
        resp = self.client.get("/api/next-task/", {"user": self.user.id})
        self.assertEqual(resp.status_code, 200)
        # attempt
        payload = {"user": self.user.id, "task": self.task.id, "is_correct": True}
        resp = self.client.post("/api/attempts/", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(resp.status_code, 201)
        # progress
        resp = self.client.get("/api/progress/", {"user": self.user.id})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["skills"]
        self.assertEqual(data[0]["mastery"], 1.0)
        self.assertEqual(data[0]["confidence"], 1.0)
