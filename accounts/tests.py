from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

User = get_user_model()


class DashboardSettingsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="user1", password="pass", email="user1@example.com"
        )

    def test_update_user_information(self):
        self.client.login(username="user1", password="pass")
        url = reverse("accounts:dashboard-settings")
        response = self.client.post(
            url,
            {
                "username": "newuser",
                "first_name": "Иван",
                "last_name": "Иванов",
                "email": "new@example.com",
                "user_submit": "",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "newuser")
        self.assertEqual(self.user.first_name, "Иван")
        self.assertEqual(self.user.last_name, "Иванов")
        self.assertEqual(self.user.email, "new@example.com")

    def test_duplicate_username_error(self):
        User.objects.create_user(
            username="user2", password="pass2", email="user2@example.com"
        )
        self.client.login(username="user1", password="pass")
        url = reverse("accounts:dashboard-settings")
        response = self.client.post(
            url,
            {
                "username": "user2",
                "first_name": "Имя",
                "last_name": "Фамилия",
                "email": "user1@example.com",
                "user_submit": "",
            },
        )
        self.assertContains(response, "Этот логин уже занят")
