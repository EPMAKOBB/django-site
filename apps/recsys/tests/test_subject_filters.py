from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.recsys.models import Subject, Skill, TaskType, Task


class SubjectFilteringTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="user")
        self.client.force_login(self.user)
        self.subj1 = Subject.objects.create(name="Math", slug="math")
        self.subj2 = Subject.objects.create(name="Physics", slug="physics")
        self.skill1 = Skill.objects.create(name="Addition", subject=self.subj1)
        self.skill2 = Skill.objects.create(name="Vectors", subject=self.subj2)
        self.type1 = TaskType.objects.create(name="Arithmetic", subject=self.subj1)
        self.type2 = TaskType.objects.create(name="Mechanics", subject=self.subj2)
        self.task1 = Task.objects.create(type=self.type1, title="Task1")
        self.task2 = Task.objects.create(type=self.type2, title="Task2")

    def test_skill_list_filtered_by_subject(self):
        resp = self.client.get("/api/skills/", {"subject": self.subj1.id})
        data = resp.json()
        if isinstance(data, dict):
            data = data.get("results", [])
        self.assertEqual([s["name"] for s in data], ["Addition"])
        resp = self.client.get("/api/skills/", {"subject": self.subj2.slug})
        data = resp.json()
        if isinstance(data, dict):
            data = data.get("results", [])
        self.assertEqual([s["name"] for s in data], ["Vectors"])

    def test_task_type_list_filtered_by_subject(self):
        resp = self.client.get("/api/task-types/", {"subject": self.subj1.id})
        data = resp.json()
        if isinstance(data, dict):
            data = data.get("results", [])
        self.assertEqual([t["name"] for t in data], ["Arithmetic"])
        resp = self.client.get("/api/task-types/", {"subject": self.subj2.slug})
        data = resp.json()
        if isinstance(data, dict):
            data = data.get("results", [])
        self.assertEqual([t["name"] for t in data], ["Mechanics"])

    def test_next_task_includes_subject(self):
        resp = self.client.get("/api/next-task/", {"user": self.user.id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["subject"]["name"], "Math")
