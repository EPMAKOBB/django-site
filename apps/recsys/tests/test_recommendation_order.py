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
from apps.recsys.recommendation import recommend_tasks


class RecommendationOrderTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="user")
        subject = Subject.objects.create(name="Math")
        exam_version = ExamVersion.objects.create(
            subject=subject, exam_type="EGE", year=2024, label="EGE 2024"
        )
        self.skill1 = Skill.objects.create(name="A", exam_version=exam_version)
        self.skill2 = Skill.objects.create(name="B", exam_version=exam_version)
        ttype = TaskType.objects.create(name="T", exam_version=exam_version)
        self.task1 = Task.objects.create(type=ttype, title="Task1")
        self.task2 = Task.objects.create(type=ttype, title="Task2")
        TaskSkill.objects.create(task=self.task1, skill=self.skill1, weight=1.0)
        TaskSkill.objects.create(task=self.task2, skill=self.skill2, weight=1.0)
        SkillMastery.objects.create(user=self.user, skill=self.skill1, mastery=0.8, confidence=1)
        SkillMastery.objects.create(user=self.user, skill=self.skill2, mastery=0.2, confidence=1)

    def test_order_lowest_mastery_first(self):
        tasks = recommend_tasks(self.user)
        self.assertEqual([t.title for t in tasks], ["Task2", "Task1"])
