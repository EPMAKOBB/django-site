from django.test import TestCase
from django.urls import reverse

from applications.utils import get_application_price


class HomeViewTests(TestCase):
    def test_default_price_in_context(self) -> None:
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context.get("application_price"), get_application_price(0)
        )
        self.assertContains(response, 'class="home-after-hero"')
        self.assertContains(response, "О проекте")
        self.assertContains(response, "О нас")
        self.assertContains(response, "Соцсети")
        self.assertContains(response, "Отзывы")
        self.assertContains(response, "Готовы начать?")

    def test_price_static_with_second_subject(self) -> None:
        response = self.client.get(reverse("home"), {"subjects": ["1", "2"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context.get("subjects_count"), 2)
        self.assertEqual(
            response.context.get("application_price"), get_application_price(2)
        )
        self.assertContains(response, 'class="home-after-hero"')
