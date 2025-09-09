from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Application
from .utils import get_application_price
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
            status="processed",
        )
        Application.objects.create(
            contact_name="New",
            grade=5,
            contact_info="info",
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
        expected_price = get_application_price(0)
        self.assertEqual(price, expected_price)
        self.assertContains(response, "price-old")
        self.assertContains(response, "price-new")
        self.assertContains(response, "при записи до 30 сентября")

    def test_get_price_group_one_subject_variant1(self) -> None:
        expected_date = date(date.today().year, 9, 30)
        price = get_application_price(1)
        self.assertEqual(
            price,
            {
                "original": 5000,
                "current": 3000,
                "promo_until": expected_date,
                "per_lesson": False,
            },
        )

    def test_get_price_group_two_subjects_variant3(self) -> None:
        expected_date = date(date.today().year, 9, 30)
        price = get_application_price(2)
        self.assertEqual(
            price,
            {
                "original": 2500,
                "current": 2000,
                "promo_until": expected_date,
                "per_lesson": True,
            },
        )

    def test_get_price_no_subjects_variant1(self) -> None:
        expected_date = date(date.today().year, 9, 30)
        price = get_application_price(0)
        self.assertEqual(
            price,
            {
                "original": 5000,
                "current": 3000,
                "promo_until": expected_date,
                "per_lesson": False,
            },
        )

    def _run_js_values(self, subject1: str, subject2: str):
        import json
        import subprocess
        from pathlib import Path

        script = f"""
        global.alert = () => {{}};
        const inputs = {{
          id_subject1: {{ value: {json.dumps(subject1)}, addEventListener: () => {{}} }},
          id_subject2: {{ value: {json.dumps(subject2)}, addEventListener: () => {{}} }},
        }};
        const priceOld = {{ textContent: '', style: {{ display: '' }} }};
        const priceNew = {{ textContent: '', style: {{ display: '' }} }};
        const priceNote = {{ textContent: '', style: {{ display: '' }} }};
        global.document = {{
          getElementById: (id) => inputs[id],
          querySelector: (sel) => sel === '.price-old' ? priceOld : sel === '.price-new' ? priceNew : priceNote,
          addEventListener: () => {{}},
        }};
        const {{ updatePrice }} = require('./static/js/main.js');
        updatePrice();
        console.log(JSON.stringify({{
          old: priceOld.textContent,
          current: priceNew.textContent,
          note: priceNote.textContent,
          oldDisplay: priceOld.style.display,
          newDisplay: priceNew.style.display,
          noteDisplay: priceNote.style.display,
        }}));
        """
        result = subprocess.run(
            ["node", "-e", script], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def _run_js(self, subject_count: int):
        subject1 = "1" if subject_count >= 1 else ""
        subject2 = "1" if subject_count >= 2 else ""
        return self._run_js_values(subject1, subject2)

    def test_js_no_subjects_variant1(self) -> None:
        data = self._run_js(0)
        self.assertEqual(
            data,
            {
                "old": "5 000 ₽/мес",
                "current": "3 000 ₽/мес",
                "note": "при записи до 30 сентября",
                "oldDisplay": "",
                "newDisplay": "",
                "noteDisplay": "",
            },
        )

    def test_js_group_one_subject_variant1(self) -> None:
        data = self._run_js(1)
        self.assertEqual(
            data,
            {
                "old": "5 000 ₽/мес",
                "current": "3 000 ₽/мес",
                "note": "при записи до 30 сентября",
                "oldDisplay": "",
                "newDisplay": "",
                "noteDisplay": "",
            },
        )

    def test_js_group_two_subjects_variant3(self) -> None:
        data = self._run_js(2)
        self.assertEqual(
            data,
            {
                "old": "2 500 ₽ за занятие (60 минут)",
                "current": "2 000 ₽ за занятие (60 минут)",
                "note": "при записи до 30 сентября",
                "oldDisplay": "",
                "newDisplay": "",
                "noteDisplay": "",
            },
        )


    def test_js_placeholder_values_not_counted(self) -> None:
        expected = {
            "old": "5 000 ₽/мес",
            "current": "3 000 ₽/мес",
            "note": "при записи до 30 сентября",
            "oldDisplay": "",
            "newDisplay": "",
            "noteDisplay": "",
        }
        for placeholder in ("0", "none"):
            with self.subTest(placeholder=placeholder, field="subject1"):
                data = self._run_js_values(placeholder, "1")
                self.assertEqual(data, expected)
            with self.subTest(placeholder=placeholder, field="subject2"):
                data = self._run_js_values("1", placeholder)
                self.assertEqual(data, expected)
