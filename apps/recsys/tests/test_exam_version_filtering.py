from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.recsys.models import (
    Attempt,
    ExamVersion,
    Skill,
    Subject,
    Task,
    TaskSkill,
    TaskType,
)


class ExamVersionFilteringTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="user")
        self.client.force_login(self.user)
        subject = Subject.objects.create(name="Math")
        self.ev1 = ExamVersion.objects.create(
            subject=subject, exam_type="EGE", year=2023, label="EGE 2023"
        )
        self.ev2 = ExamVersion.objects.create(
            subject=subject, exam_type="EGE", year=2024, label="EGE 2024"
        )
        self.skill1 = Skill.objects.create(name="S1", exam_version=self.ev1)
        self.ttype1 = TaskType.objects.create(name="T1", exam_version=self.ev1)
        self.task1 = Task.objects.create(type=self.ttype1, title="Task1")
        TaskSkill.objects.create(task=self.task1, skill=self.skill1)
        self.skill2 = Skill.objects.create(name="S2", exam_version=self.ev2)
        self.ttype2 = TaskType.objects.create(name="T2", exam_version=self.ev2)
        self.task2 = Task.objects.create(type=self.ttype2, title="Task2")
        TaskSkill.objects.create(task=self.task2, skill=self.skill2)

    def test_skill_list_filtered(self):
        resp = self.client.get("/api/skills/", {"exam_version": self.ev1.id})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], self.skill1.id)

    def test_next_task_filtered(self):
        resp = self.client.get("/api/next-task/", {"exam_version": self.ev2.id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], self.task2.id)

    def test_progress_filtered(self):
        Attempt.objects.create(user=self.user, task=self.task1, is_correct=True)
        Attempt.objects.create(user=self.user, task=self.task2, is_correct=False)
        resp = self.client.get("/api/progress/", {"exam_version": self.ev1.id})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["attempts"]["total"], 1)
        self.assertEqual(data["attempts"]["correct"], 1)
        self.assertEqual(len(data["skill_masteries"]), 1)
        self.assertEqual(data["skill_masteries"][0]["skill"]["id"], self.skill1.id)
