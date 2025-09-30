from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch

User = get_user_model()


class ParserControlViewTests(TestCase):
    def setUp(self):
        self.url = reverse("parser_tasks:control")

    def test_requires_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.headers["Location"])

    def test_requires_superuser(self):
        user = User.objects.create_user(username="user", password="testpass")
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_superuser_can_view(self):
        superuser = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="testpass"
        )
        self.client.force_login(superuser)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Запуск парсера заданий")

    @patch("parser_tasks.views.run_parser")
    def test_superuser_can_start_parser(self, run_parser_mock):
        run_parser_mock.return_value.tasks_count = 5
        superuser = User.objects.create_superuser(
            username="boss", email="boss@example.com", password="testpass"
        )
        self.client.force_login(superuser)
        response = self.client.post(
            self.url,
            {"source_url": "https://example.com"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        run_parser_mock.assert_called_once_with("https://example.com")
        self.assertContains(response, "Парсинг завершен")
