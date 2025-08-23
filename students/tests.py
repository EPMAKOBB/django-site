"""Tests for the students app."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Assignment, Course, Submission


class DashboardViewTests(TestCase):
    """Verify access control and progress display on the dashboard."""

    def setUp(self):
        User = get_user_model()
        self.student = User.objects.create_user("student", password="pass")
        self.staff = User.objects.create_user(
            "staff", password="pass", is_staff=True
        )
        self.course = Course.objects.create(title="Math")
        self.assignment = Assignment.objects.create(
            course=self.course, title="HW1", description=""
        )

    def test_login_required(self):
        response = self.client.get(reverse("students:dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_staff_forbidden(self):
        self.client.login(username="staff", password="pass")
        response = self.client.get(reverse("students:dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_progress_display(self):
        self.client.login(username="student", password="pass")
        Submission.objects.create(
            assignment=self.assignment, student=self.student
        )
        response = self.client.get(reverse("students:dashboard"))
        self.assertEqual(response.status_code, 200)
        course_data = response.context["course_data"][0]
        self.assertEqual(course_data["completed"], 1)
        self.assertEqual(course_data["total"], 1)

