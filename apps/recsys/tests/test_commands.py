from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

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
        subject = Subject.objects.get(name="Математика")
        exam_version = ExamVersion.objects.get(name="ЕГЭ 2026", subject=subject)
        self.assertEqual(TaskType.objects.filter(subject=subject).count(), 27)
        self.assertEqual(Skill.objects.filter(subject=subject).count(), 27)
        self.assertEqual(
            Task.objects.filter(subject=subject, exam_version=exam_version).count(), 27
        )
        self.assertEqual(TaskSkill.objects.count(), 27)


class RecomputeMasteryCommandTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="user")
        self.subject = Subject.objects.create(name="Subject")
        self.exam_version = ExamVersion.objects.create(name="V1", subject=self.subject)
        self.skill = Skill.objects.create(name="Skill", subject=self.subject)
        self.task_type = TaskType.objects.create(name="Type", subject=self.subject)
        self.task = Task.objects.create(
            type=self.task_type,
            title="Task",
            subject=self.subject,
            exam_version=self.exam_version,
        )
        TaskSkill.objects.create(task=self.task, skill=self.skill)
        first = Attempt.objects.create(user=self.user, task=self.task, is_correct=True)
        first.created_at = timezone.now() - timedelta(minutes=10)
        first.save(update_fields=["created_at"])
        Attempt.objects.create(user=self.user, task=self.task, is_correct=False)

    def test_recompute_mastery_all_users(self):
        call_command("recompute_mastery")
        sm = SkillMastery.objects.get(user=self.user, skill=self.skill)
        tm = TypeMastery.objects.get(user=self.user, task_type=self.task_type)
        self.assertAlmostEqual(sm.mastery, 0.5)
        self.assertAlmostEqual(tm.mastery, 0.5)
        self.assertEqual(sm.skill.subject, self.subject)
        self.assertEqual(self.task.exam_version.subject, self.subject)

    def test_recompute_mastery_single_user(self):
        other_user = get_user_model().objects.create(username="other")
        call_command("recompute_mastery", user=str(self.user.pk))
        self.assertTrue(
            SkillMastery.objects.filter(user=self.user, skill=self.skill).exists()
        )
        self.assertFalse(
            SkillMastery.objects.filter(user=other_user, skill=self.skill).exists()
        )
