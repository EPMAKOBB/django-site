from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.recsys.models import ExamVersion, SkillGroup


class SkillGroupSeedTests(TestCase):
    def test_seed_creates_groups(self):
        call_command("seed_ege")
        exam = ExamVersion.objects.get(name="ЕГЭ 2026")
        groups = SkillGroup.objects.filter(exam_version=exam).order_by("title")
        self.assertEqual(groups.count(), 2)

        algebra = groups.get(title="Алгебра")
        items = list(algebra.items.order_by("order"))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].skill.name, "Skill 1")
        self.assertEqual(items[0].label, "Линейные уравнения")
        self.assertEqual(items[0].order, 1)
        self.assertEqual(items[1].skill.name, "Skill 2")
        self.assertEqual(items[1].label, "Квадратные уравнения")


class SkillGroupAPITests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="user")
        call_command("seed_ege")
        self.exam = ExamVersion.objects.get(name="ЕГЭ 2026")

    def test_api_returns_groups(self):
        self.client.force_login(self.user)
        resp = self.client.get(f"/api/skill-groups/{self.exam.id}/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 2)
        algebra = next(group for group in data if group["title"] == "Алгебра")
        self.assertEqual(len(algebra["items"]), 2)
        first_item = algebra["items"][0]
        self.assertEqual(first_item["label"], "Линейные уравнения")
        self.assertEqual(first_item["order"], 1)
        self.assertEqual(first_item["skill"]["name"], "Skill 1")
