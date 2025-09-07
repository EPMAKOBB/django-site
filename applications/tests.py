from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Application
from subjects.models import Subject


class ApplicationTests(TestCase):
    def setUp(self) -> None:
        self.subject_math = Subject.objects.create(name="Math", slug="math")
        self.subject_physics = Subject.objects.create(name="Physics", slug="physics")

    def test_application_form_submission_with_multiple_subjects(self) -> None:
        data = {
            "contact_name": "Parent",
            "student_name": "Student",
            "grade": 9,
            "subject1": self.subject_math.id,
            "subject2": self.subject_physics.id,
            "contact_info": "email@example.com",
            "lesson_type": "individual",
            "source_offer": "math-9",
        }
        response = self.client.post(reverse("applications:apply"), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Application.objects.count(), 1)
        app = Application.objects.first()
        assert app is not None
        self.assertEqual(app.subjects.count(), 2)

    def test_admin_filter_by_status(self) -> None:
        Application.objects.create(
            contact_name="Processed",
            grade=5,
            contact_info="info",
            lesson_type="individual",
            status="processed",
        )
        Application.objects.create(
            contact_name="New",
            grade=5,
            contact_info="info",
            lesson_type="individual",
        )
        admin_user = get_user_model().objects.create_superuser(
            "admin", "admin@example.com", "password"
        )
        self.client.force_login(admin_user)
        url = reverse("admin:applications_application_changelist")
        response = self.client.get(url, {"status__exact": "processed"})
        cl = response.context.get("cl")
        self.assertIsNotNone(cl)
        if cl:
            self.assertEqual(cl.queryset.count(), 1)
            self.assertEqual(cl.queryset.first().contact_name, "Processed")


class ApplicationPriceTests(TestCase):
    def test_default_price_in_context(self) -> None:
        response = self.client.get(reverse("applications:apply"))
        self.assertEqual(response.status_code, 200)
        price = response.context.get("application_price")
        expected_date = date(date.today().year, 9, 30)
        self.assertEqual(
            price,
            {
                "original": 5000,
                "current": 3000,
                "promo_until": expected_date,
            },
        )
