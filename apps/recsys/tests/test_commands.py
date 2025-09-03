from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.recsys.models import (
    Attempt,
    ExamVersion,
    Skill,
    SkillMastery,
    Subject,
    Task,
    TaskSkill,
    TaskType,
    TypeMastery,
)


class SeedEGECommandTest(TestCase):
    def test_seed_ege_populates_data(self):
        call_command("seed_ege")
        self.assertEqual(TaskType.objects.count(), 27)
        self.assertEqual(Skill.objects.count(), 27)
        self.assertEqual(Task.objects.count(), 27)
        self.assertEqual(TaskSkill.objects.count(), 27)
        self.assertEqual(Subject.objects.count(), 1)
        self.assertEqual(ExamVersion.objects.count(), 1)


class RecomputeMasteryCommandTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="user")
        subject = Subject.objects.create(name="Math")
        exam_version = ExamVersion.objects.create(
            subject=subject, exam_type="EGE", year=2024, label="EGE 2024"
        )
        self.skill = Skill.objects.create(name="Skill", exam_version=exam_version)
        self.task_type = TaskType.objects.create(name="Type", exam_version=exam_version)
        self.task = Task.objects.create(type=self.task_type, title="Task")
        TaskSkill.objects.create(task=self.task, skill=self.skill)
        old = Attempt.objects.create(user=self.user, task=self.task, is_correct=True)
        old.created_at = timezone.now() - timedelta(minutes=10)
        old.save(update_fields=["created_at"])
        Attempt.objects.create(user=self.user, task=self.task, is_correct=False)

    def test_recompute_mastery_all_users(self):
        call_command("recompute_mastery")
        sm = SkillMastery.objects.get(user=self.user, skill=self.skill)
        tm = TypeMastery.objects.get(user=self.user, task_type=self.task_type)
        self.assertAlmostEqual(sm.mastery, 0.5)
        self.assertAlmostEqual(tm.mastery, 0.5)

    def test_recompute_mastery_single_user(self):
        other_user = get_user_model().objects.create(username="other")
        call_command("recompute_mastery", user=str(self.user.pk))
        self.assertTrue(
            SkillMastery.objects.filter(user=self.user, skill=self.skill).exists()
        )
        self.assertFalse(
            SkillMastery.objects.filter(user=other_user, skill=self.skill).exists()
        )
