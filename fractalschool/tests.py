from django.test import TestCase
from django.urls import reverse

class HomeViewTests(TestCase):
    def test_home_has_direct_contact_and_compact_sections(self) -> None:
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="https://t.me/EPMAKO"')
        self.assertContains(response, 'href="https://wa.me/79296435092"')
        self.assertContains(response, 'href="tel:+79296435092"')
        self.assertContains(response, "О школе")
        self.assertContains(response, "Отзывы")
        self.assertNotContains(response, "Готовы начать?")
        self.assertNotContains(response, '<form')
        self.assertNotIn("form", response.context)
        self.assertNotIn("application_price", response.context)

    def test_legacy_application_query_does_not_change_home(self) -> None:
        response = self.client.get(reverse("home"), {"subjects": ["1", "2"]})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Готовиться с учителем")
        self.assertNotIn("subjects_count", response.context)
