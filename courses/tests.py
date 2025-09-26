from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import (
    Course,
    CourseEnrollment,
    CourseModule,
    CourseModuleItem,
    CourseTheoryCard,
)


class ModuleDetailViewTests(TestCase):
    """Tests for the course module detail view."""

    def setUp(self) -> None:
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="student",
            email="student@example.com",
            password="password123",
        )
        self.other_user = user_model.objects.create_user(
            username="outsider",
            email="outsider@example.com",
            password="password123",
        )

        self.course = Course.objects.create(
            slug="math",
            title="Математика",
        )
        self.module = CourseModule.objects.create(
            course=self.course,
            slug="module-1",
            title="Основы",
            kind=CourseModule.Kind.SELF_PACED,
            rank=1,
        )

        self.card_intro = CourseTheoryCard.objects.create(
            course=self.course,
            slug="intro",
            title="Введение",
            content="Первый шаг",
        )
        self.card_next = CourseTheoryCard.objects.create(
            course=self.course,
            slug="deep-dive",
            title="Продвинутый материал",
            content="Продолжаем обучение",
        )

        CourseModuleItem.objects.create(
            module=self.module,
            kind=CourseModuleItem.ItemKind.THEORY,
            theory_card=self.card_intro,
            position=1,
            min_mastery_percent=0,
            max_mastery_percent=30,
        )
        CourseModuleItem.objects.create(
            module=self.module,
            kind=CourseModuleItem.ItemKind.THEORY,
            theory_card=self.card_next,
            position=2,
            min_mastery_percent=31,
            max_mastery_percent=100,
        )

        self.enrollment = CourseEnrollment.objects.create(
            course=self.course,
            student=self.user,
            status=CourseEnrollment.Status.ENROLLED,
            progress=0,
        )

    def test_requires_enrollment(self) -> None:
        """Users without an enrollment cannot access the module."""

        self.client.login(username="outsider", password="password123")
        response = self.client.get(
            reverse("courses:module-detail", args=[self.course.slug, self.module.slug])
        )
        self.assertEqual(response.status_code, 403)

    def test_selects_item_based_on_mastery(self) -> None:
        """The item selected in the context matches the mastery thresholds."""

        self.enrollment.progress = 45
        self.enrollment.save(update_fields=["progress"])

        self.client.login(username="student", password="password123")
        response = self.client.get(
            reverse("courses:module-detail", args=[self.course.slug, self.module.slug])
        )
        self.assertEqual(response.status_code, 200)
        current_item = response.context["current_item"]
        self.assertIsNotNone(current_item)
        self.assertEqual(current_item.theory_card, self.card_next)
        self.assertContains(response, self.card_next.title)
        self.assertContains(response, "Мастерство")
