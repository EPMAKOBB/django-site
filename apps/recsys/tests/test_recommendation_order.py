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
from apps.recsys.recommendation import recommend_tasks


class RecommendationOrderTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="user")
        self.subject = Subject.objects.create(name="Subject")
        self.exam_version = ExamVersion.objects.create(name="V1", subject=self.subject)
        self.skill1 = Skill.objects.create(name="A", subject=self.subject)
        self.skill2 = Skill.objects.create(name="B", subject=self.subject)
        ttype = TaskType.objects.create(name="T", subject=self.subject)
        self.task1 = Task.objects.create(
            type=ttype, title="Task1", subject=self.subject, exam_version=self.exam_version
        )
        self.task2 = Task.objects.create(
            type=ttype, title="Task2", subject=self.subject, exam_version=self.exam_version
        )
        TaskSkill.objects.create(task=self.task1, skill=self.skill1, weight=1.0)
        TaskSkill.objects.create(task=self.task2, skill=self.skill2, weight=1.0)
        SkillMastery.objects.create(user=self.user, skill=self.skill1, mastery=0.8, confidence=1)
        SkillMastery.objects.create(user=self.user, skill=self.skill2, mastery=0.2, confidence=1)

    def test_order_lowest_mastery_first(self):
        tasks = recommend_tasks(self.user)
        self.assertEqual([t.title for t in tasks], ["Task2", "Task1"])
        for task in tasks:
            self.assertEqual(task.subject, self.subject)
            self.assertEqual(task.exam_version, self.exam_version)
