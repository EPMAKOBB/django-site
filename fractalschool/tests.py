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
        self.assertContains(response, "price-old")
        self.assertContains(response, "price-new")
        self.assertContains(response, "при записи до 30 сентября")
