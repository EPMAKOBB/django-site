from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from parser_tasks.services import run_parser

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


class ParserServiceTests(TestCase):
    @patch("parser_tasks.services.requests.get")
    def test_run_parser_preserves_html_markup(self, get_mock):
        html_source = """
        <html>
          <body>
            <div class="problem">
              <div class="problem_text">
                <p>См. рисунок</p>
                <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">
                  <circle cx="5" cy="5" r="4" />
                </svg>
              </div>
              <div class="answer">Ответ: 42</div>
            </div>
          </body>
        </html>
        """

        get_mock.return_value = SimpleNamespace(
            text=html_source,
            status_code=200,
            raise_for_status=lambda: None,
        )

        result = run_parser("https://example.com/test")

        self.assertEqual(result.tasks_count, 1)
        parsed_task = result.tasks[0]
        self.assertIn("<svg", parsed_task.text)
        self.assertIn("</svg>", parsed_task.text)
        self.assertIn("См. рисунок", parsed_task.text)
        self.assertEqual(parsed_task.answer, "Ответ: 42")
