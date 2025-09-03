from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.recsys.models import (
    Attempt,
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


class RecomputeMasteryCommandTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="user")
        self.subject = Subject.objects.create(name="Subject")
        self.skill = Skill.objects.create(name="Skill", subject=self.subject)
        self.task_type = TaskType.objects.create(name="Type", subject=self.subject)
        self.task = Task.objects.create(type=self.task_type, title="Task")
        TaskSkill.objects.create(task=self.task, skill=self.skill)
        Attempt.objects.create(user=self.user, task=self.task, is_correct=True)
        Attempt.objects.create(user=self.user, task=self.task, is_correct=False)

    def test_recompute_mastery_all_users(self):
        call_command("recompute_mastery")
        sm = SkillMastery.objects.get(user=self.user, skill=self.skill)
        tm = TypeMastery.objects.get(user=self.user, task_type=self.task_type)
        self.assertAlmostEqual(sm.mastery, 0.0)
        self.assertAlmostEqual(tm.mastery, 0.0)

    def test_recompute_mastery_single_user(self):
        other_user = get_user_model().objects.create(username="other")
        call_command("recompute_mastery", user=str(self.user.pk))
        self.assertTrue(
            SkillMastery.objects.filter(user=self.user, skill=self.skill).exists()
        )
        self.assertFalse(
            SkillMastery.objects.filter(user=other_user, skill=self.skill).exists()
        )
