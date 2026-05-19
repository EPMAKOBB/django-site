from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.recsys.models import (
    Attempt,
    ExamVersion,
    TrainingSession,
    TrainingSessionStep,
    VariantAssignment,
    VariantAttempt,
    VariantTemplate,
    VariantTaskAttempt,
)
from apps.recsys.tests import factories as variant_factories

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

    def test_dashboard_settings_does_not_show_exam_selection(self):
        self.client.login(username="user1", password="pass")
        response = self.client.get(reverse("accounts:dashboard-settings"))

        self.assertNotContains(response, "Выбор экзаменов")
        self.assertNotContains(response, "exam_versions")
        self.assertNotContains(response, "Сохранить выбор")


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

        personal_assignment, personal_variant_tasks = self._create_assignment(
            deadline=future_deadline,
            max_attempts=None,
        )
        personal_assignment.template.kind = VariantTemplate.Kind.PERSONAL
        personal_assignment.template.save(update_fields=["kind"])
        personal_attempt = VariantAttempt.objects.create(
            assignment=personal_assignment,
            attempt_number=1,
            completed_at=timezone.now() - timedelta(minutes=10),
            time_spent=timedelta(minutes=20),
        )
        VariantTaskAttempt.objects.create(
            variant_attempt=personal_attempt,
            variant_task=personal_variant_tasks[0],
            task=personal_variant_tasks[0].task,
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
            {past_assignment.pk, personal_assignment.pk},
        )

        active_info = next(
            item for item in current_assignments if item["assignment"].pk == active_assignment.pk
        )
        self.assertEqual(active_info["progress"]["solved_tasks"], 1)
        self.assertIsNotNone(active_info["active_attempt"])
        self.assertFalse(active_info["can_start"])

        past_info = next(
            item for item in past_assignments if item["assignment"].pk == past_assignment.pk
        )
        self.assertTrue(past_info["deadline_passed"])

        personal_info = next(
            item for item in past_assignments if item["assignment"].pk == personal_assignment.pk
        )
        self.assertFalse(personal_info["can_start"])

    def test_dashboard_shows_training_sessions(self):
        task = variant_factories.create_task(title="Training task")
        exam = ExamVersion.objects.create(subject=task.subject, name="Training exam", slug="training-exam")
        task.exam_version = exam
        task.save(update_fields=["exam_version"])
        session = TrainingSession.objects.create(
            user=self.user,
            exam_version=exam,
            status=TrainingSession.Status.COMPLETED,
            completed_steps=1,
            correct_steps=1,
            steps_total=1,
            last_activity_at=timezone.now(),
            ended_at=timezone.now(),
        )
        attempt = Attempt.objects.create(
            user=self.user,
            task=task,
            mode=Attempt.Mode.TRAINING,
            is_correct=True,
            score=1,
            max_score=1,
            is_valid_attempt=True,
            checked_at=timezone.now(),
        )
        TrainingSessionStep.objects.create(
            session=session,
            order=1,
            task=task,
            attempt=attempt,
            status=TrainingSessionStep.Status.ANSWERED,
            result=TrainingSessionStep.Result.CORRECT,
            task_snapshot={
                "title": task.title,
                "task_type_name": task.type.name,
                "max_score": 1,
            },
            response_snapshot={"answer": "42"},
            answered_at=timezone.now(),
        )

        response = self.client.get(reverse("accounts:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["past_training_sessions"]), 1)
        self.assertContains(response, "Training task")
        self.assertContains(response, "Training exam")
        self.assertContains(response, "1")

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

        assignment.refresh_from_db()
        self.assertEqual(assignment.attempts.count(), 1)
        attempt = assignment.attempts.first()
        self.assertEqual(
            response["Location"],
            reverse("accounts:variant-attempt-solver", args=[attempt.pk]),
        )
        self.assertEqual(attempt.attempt_number, 1)
        self.assertIsNotNone(attempt.started_at)

    def test_attempt_work_route_redirects_to_solver(self):
        assignment, _ = self._create_assignment()
        attempt = VariantAttempt.objects.create(
            assignment=assignment,
            attempt_number=1,
        )

        response = self.client.get(reverse("accounts:variant-attempt-work", args=[attempt.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("accounts:variant-attempt-solver", args=[attempt.pk]),
        )

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
