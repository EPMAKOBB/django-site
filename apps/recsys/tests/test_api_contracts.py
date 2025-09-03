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
)


class ApiContractsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="user")
        self.client.force_login(self.user)
        self.subject = Subject.objects.create(name="Subject")
        self.exam_version = ExamVersion.objects.create(name="V1", subject=self.subject)
        self.skill = Skill.objects.create(name="Skill", subject=self.subject)
        self.ttype = TaskType.objects.create(name="Type", subject=self.subject)
        self.task = Task.objects.create(
            type=self.ttype,
            title="Task",
            subject=self.subject,
            exam_version=self.exam_version,
        )
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
        data = resp.json()["skill_masteries"]
        self.assertEqual(data[0]["mastery"], 1.0)
        self.assertEqual(self.task.subject, self.subject)
        self.assertEqual(self.task.exam_version, self.exam_version)
