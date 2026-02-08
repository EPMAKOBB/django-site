from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import TeacherStudentLink
from subjects.models import Subject


class TeacherUserAccessTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.teacher = self.user_model.objects.create_user(username="teacher", password="pass")
        self.student = self.user_model.objects.create_user(username="student", password="pass")
        self.subject = Subject.objects.create(name="Math")

    def test_teacher_user_requires_link_or_staff(self):
        self.client.force_login(self.teacher)
        url = reverse("recsys_teacher_user", kwargs={"user_id": self.student.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_teacher_user_allows_active_link(self):
        TeacherStudentLink.objects.create(
            teacher=self.teacher,
            student=self.student,
            subject=self.subject,
            status=TeacherStudentLink.Status.ACTIVE,
        )
        self.client.force_login(self.teacher)
        url = reverse("recsys_teacher_user", kwargs={"user_id": self.student.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_teacher_user_allows_staff(self):
        staff = self.user_model.objects.create_user(
            username="staff", password="pass", is_staff=True
        )
        self.client.force_login(staff)
        url = reverse("recsys_teacher_user", kwargs={"user_id": self.student.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
