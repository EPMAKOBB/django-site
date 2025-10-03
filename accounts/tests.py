from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import StudentProfile
from apps.recsys.models import (
    ExamVersion,
    Skill,
    SkillGroup,
    SkillGroupItem,
    SkillMastery,
    VariantAssignment,
    VariantAttempt,
    VariantTaskAttempt,
)
from apps.recsys.tests import factories as variant_factories
from subjects.models import Subject

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

    def test_progress_bar_displays_skill_mastery_value(self):
        subject = Subject.objects.create(name="Математика", slug="matematika")
        exam = ExamVersion.objects.create(subject=subject, name="Вариант 1")
        profile, _ = StudentProfile.objects.get_or_create(user=self.user)
        profile.exam_versions.set([exam])

        skill = Skill.objects.create(subject=subject, name="Линейные уравнения")
        group = SkillGroup.objects.create(exam_version=exam, title="Алгебра")
        SkillGroupItem.objects.create(
            group=group,
            skill=skill,
            label="Уравнения",
            order=1,
        )
        SkillMastery.objects.create(user=self.user, skill=skill, mastery=0.52)

        self.client.login(username="student", password="pass")
        response = self.client.get(reverse("accounts:dashboard-subjects"))

        content = response.content.decode("utf-8")
        self.assertIn("Линейные уравнения", content)
        self.assertIn("52%", content)
        self.assertIn('style="width: 52', content)


class DashboardAssignmentsViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="student_assignments",
            password="pass",
            email="assignments@example.com",
        )
        self.client.login(username="student_assignments", password="pass")

    def _create_assignment(self, *, user=None, max_attempts=2, deadline=None):
        template = variant_factories.create_variant_template(max_attempts=max_attempts)
        task_one = variant_factories.create_task()
        task_two = variant_factories.create_task()
        variant_factories.add_variant_task(template=template, task=task_one, order=1)
        variant_factories.add_variant_task(template=template, task=task_two, order=2)

        assignment = VariantAssignment.objects.create(
            template=template,
            user=user or self.user,
            deadline=deadline,
        )
        return assignment, list(template.template_tasks.all())

    def test_assignments_are_split_into_current_and_past(self):
        future_deadline = timezone.now() + timedelta(days=3)
        past_deadline = timezone.now() - timedelta(days=1)

        open_assignment, _ = self._create_assignment(deadline=future_deadline, max_attempts=3)

        active_assignment, active_variant_tasks = self._create_assignment(
            deadline=future_deadline,
            max_attempts=3,
        )
        active_attempt = VariantAttempt.objects.create(
            assignment=active_assignment,
            attempt_number=1,
        )
        VariantTaskAttempt.objects.create(
            variant_attempt=active_attempt,
            variant_task=active_variant_tasks[0],
            task=active_variant_tasks[0].task,
            attempt_number=1,
            is_correct=True,
        )

        past_assignment, past_variant_tasks = self._create_assignment(
            deadline=past_deadline,
            max_attempts=1,
        )
        VariantAttempt.objects.create(
            assignment=past_assignment,
            attempt_number=1,
            completed_at=timezone.now() - timedelta(hours=1),
            time_spent=timedelta(minutes=30),
        )
        VariantTaskAttempt.objects.create(
            variant_attempt=past_assignment.attempts.first(),
            variant_task=past_variant_tasks[0],
            task=past_variant_tasks[0].task,
            attempt_number=1,
            is_correct=True,
        )

        other_user = User.objects.create_user(
            username="other-student",
            password="pass",
        )
        self._create_assignment(user=other_user)

        response = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(response.status_code, 200)

        current_assignments = response.context["current_assignments"]
        past_assignments = response.context["past_assignments"]

        self.assertSetEqual(
            {item["assignment"].pk for item in current_assignments},
            {open_assignment.pk, active_assignment.pk},
        )
        self.assertSetEqual(
            {item["assignment"].pk for item in past_assignments},
            {past_assignment.pk},
        )

        active_info = next(
            item for item in current_assignments if item["assignment"].pk == active_assignment.pk
        )
        self.assertEqual(active_info["progress"]["solved_tasks"], 1)
        self.assertIsNotNone(active_info["active_attempt"])
        self.assertFalse(active_info["can_start"])

        past_info = past_assignments[0]
        self.assertTrue(past_info["deadline_passed"])

    def test_assignment_detail_permissions_and_context(self):
        assignment, _ = self._create_assignment()
        url = reverse("accounts:assignment-detail", args=[assignment.pk])

        self.client.logout()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

        other_user = User.objects.create_user(
            username="second-student",
            password="pass",
        )
        self.client.login(username="second-student", password="pass")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

        self.client.login(username="student_assignments", password="pass")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["assignment"], assignment)
        self.assertIn("progress", response.context["assignment_info"])

    def test_assignment_detail_start_attempt(self):
        assignment, _ = self._create_assignment()
        url = reverse("accounts:assignment-detail", args=[assignment.pk])

        response = self.client.post(url, {"start_attempt": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], url)

        assignment.refresh_from_db()
        self.assertEqual(assignment.attempts.count(), 1)
        attempt = assignment.attempts.first()
        self.assertEqual(attempt.attempt_number, 1)
        self.assertIsNotNone(attempt.started_at)

    def test_assignment_result_contains_attempts(self):
        assignment, variant_tasks = self._create_assignment()
        attempt = VariantAttempt.objects.create(
            assignment=assignment,
            attempt_number=1,
            completed_at=timezone.now(),
            time_spent=timedelta(minutes=15),
        )
        VariantTaskAttempt.objects.create(
            variant_attempt=attempt,
            variant_task=variant_tasks[0],
            task=variant_tasks[0].task,
            attempt_number=1,
            is_correct=True,
        )

        url = reverse("accounts:assignment-result", args=[assignment.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["assignment"], assignment)
        self.assertEqual(len(response.context["attempts"]), 1)

        other_user = User.objects.create_user("forbidden", password="pass")
        self.client.login(username="forbidden", password="pass")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
