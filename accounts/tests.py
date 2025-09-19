from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from accounts.models import StudentProfile
from subjects.models import Subject
from apps.recsys.models import ExamVersion

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

    def test_dashboard_settings_shows_selected_exam_versions(self):
        subject = Subject.objects.create(name="Математика", slug="matematika")
        exam_first = ExamVersion.objects.create(subject=subject, name="Пробный вариант 1")
        exam_second = ExamVersion.objects.create(subject=subject, name="Пробный вариант 2")

        profile, _ = StudentProfile.objects.get_or_create(user=self.user)
        profile.exam_versions.set([exam_first, exam_second])

        self.client.login(username="user1", password="pass")
        response = self.client.get(reverse("accounts:dashboard-settings"))

        self.assertContains(
            response,
            f'value="{exam_first.id}" checked="checked"',
            html=False,
        )
        self.assertContains(
            response,
            f'value="{exam_second.id}" checked="checked"',
            html=False,
        )
        self.assertNotContains(response, "Ваши экзамены")
        self.assertNotContains(response, "Математика — Пробный вариант 1")
        self.assertNotContains(response, "Математика — Пробный вариант 2")
        self.assertNotContains(response, "выбрать экзамены можно")

    def test_exam_selection_submission_without_choices_clears_profile(self):
        subject = Subject.objects.create(name="Математика", slug="matematika")
        ExamVersion.objects.create(subject=subject, name="Пробный вариант 1")
        profile, _ = StudentProfile.objects.get_or_create(user=self.user)
        profile.exam_versions.set(list(subject.exam_versions.all()))

        self.client.login(username="user1", password="pass")
        url = reverse("accounts:dashboard-settings")

        with self.assertLogs("accounts", level="DEBUG") as logs:
            response = self.client.post(url, {"form_type": "exams"})

        self.assertEqual(response.status_code, 302)
        profile = StudentProfile.objects.get(pk=profile.pk)
        self.assertEqual(profile.exam_versions.count(), 0)
        self.assertTrue(
            any("Received exam selection payload" in message for message in logs.output)
        )

    def test_exam_selection_without_submit_keys_updates_profile(self):
        subject = Subject.objects.create(name="Математика", slug="matematika")
        exam = ExamVersion.objects.create(subject=subject, name="Пробный вариант 1")

        self.client.login(username="user1", password="pass")
        url = reverse("accounts:dashboard-settings")
        response = self.client.post(url, {"exam_versions": [str(exam.id)]})

        self.assertRedirects(response, url)

        profile = StudentProfile.objects.get(user=self.user)
        self.assertEqual(list(profile.exam_versions.all()), [exam])


class DashboardSubjectsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="student", password="pass", email="student@example.com"
        )

    def test_only_selected_exam_is_displayed(self):
        subject = Subject.objects.create(name="Математика", slug="matematika")
        selected_exam = ExamVersion.objects.create(
            subject=subject, name="Вариант 1"
        )
        other_exam = ExamVersion.objects.create(subject=subject, name="Вариант 2")

        profile, _ = StudentProfile.objects.get_or_create(user=self.user)
        profile.exam_versions.set([selected_exam])

        self.client.login(username="student", password="pass")

        response = self.client.get(reverse("accounts:dashboard-subjects"))

        self.assertContains(
            response,
            f"{subject.name} — {selected_exam.name}",
        )
        self.assertNotContains(response, other_exam.name)
