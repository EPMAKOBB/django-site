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
        self.assertContains(response, "занятия в группе: 3 000 ₽/мес")
        self.assertContains(response, "занятия индивидуальные: 2 000 ₽/60 минут")

    def test_price_static_with_second_subject(self) -> None:
        response = self.client.get(
            reverse("home"), {"subject1": "1", "subject2": "1"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context.get("application_price"), get_application_price(2)
        )
        self.assertContains(response, "занятия в группе: 3 000 ₽/мес")
        self.assertContains(response, "занятия индивидуальные: 2 000 ₽/60 минут")

