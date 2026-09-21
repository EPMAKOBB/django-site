from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import TeacherProfile, TeacherStudentLink
from lessons.services import create_lesson
from lessons.forms import LessonCreateForm
from subjects.models import Subject

from .models import StudentRecord
from .services import accept_account_invite, create_account_invite


class UnregisteredStudentFlowTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.teacher = user_model.objects.create_user(username="teacher", password="pass")
        TeacherProfile.objects.create(user=self.teacher)
        self.subject = Subject.objects.create(name="Математика", slug="math-student-record")

    def test_teacher_creates_unregistered_student_from_dashboard(self):
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse("accounts:dashboard-students"),
            {
                "action": "create_student",
                "full_name": "Анна Иванова",
                "status": StudentRecord.Status.ACTIVE,
                "grade": 9,
                "subject": self.subject.pk,
                "timezone": "Asia/Yekaterinburg",
                "default_duration_minutes": 60,
                "default_price_amount": "2000.00",
                "contact_name": "Мария Иванова",
                "contact_phone": "+79990000000",
                "relationship": "mother",
            },
        )
        self.assertRedirects(response, reverse("accounts:dashboard-students"))
        student = StudentRecord.objects.get(full_name="Анна Иванова")
        self.assertIsNone(student.user_id)
        link = TeacherStudentLink.objects.get(student_record=student)
        self.assertIsNone(link.student_id)
        self.assertEqual(link.default_price_amount, Decimal("2000.00"))
        self.assertEqual(student.contact_links.get().contact.phone, "+79990000000")

    def test_unregistered_student_can_have_lessons(self):
        student = StudentRecord.objects.create(
            full_name="Без аккаунта",
            status=StudentRecord.Status.ACTIVE,
            created_by=self.teacher,
        )
        link = TeacherStudentLink.objects.create(
            teacher=self.teacher,
            student_record=student,
            subject=self.subject,
            status=TeacherStudentLink.Status.ACTIVE,
        )
        lesson = create_lesson(
            link=link,
            scheduled_start=datetime(2026, 9, 7, 16, 0, tzinfo=datetime_timezone.utc),
            duration_minutes=60,
            price_amount=Decimal("2000.00"),
            created_by=self.teacher,
        )
        self.assertEqual(lesson.teacher_student_link.student_display_name, "Без аккаунта")

    def test_invite_binds_existing_record_without_changing_lessons(self):
        user_model = get_user_model()
        account = user_model.objects.create_user(username="anna", password="pass")
        student = StudentRecord.objects.create(full_name="Анна", created_by=self.teacher)
        link = TeacherStudentLink.objects.create(
            teacher=self.teacher,
            student_record=student,
            subject=self.subject,
            status=TeacherStudentLink.Status.ACTIVE,
        )
        _, raw_token = create_account_invite(student=student, created_by=self.teacher)

        accepted = accept_account_invite(raw_token=raw_token, user=account)

        link.refresh_from_db()
        self.assertEqual(accepted.user, account)
        self.assertEqual(link.student, account)

    def test_other_teacher_cannot_edit_student_card(self):
        user_model = get_user_model()
        other_teacher = user_model.objects.create_user(username="other", password="pass")
        TeacherProfile.objects.create(user=other_teacher)
        student = StudentRecord.objects.create(full_name="Чужой ученик", created_by=self.teacher)
        self.client.force_login(other_teacher)
        response = self.client.get(reverse("students:edit", args=[student.public_id]))
        self.assertEqual(response.status_code, 403)

    def _student_with_subject(self):
        student = StudentRecord.objects.create(full_name="Анна Иванова", created_by=self.teacher)
        link = TeacherStudentLink.objects.create(
            teacher=self.teacher, student_record=student, subject=self.subject,
            status=TeacherStudentLink.Status.ACTIVE, default_duration_minutes=60,
            default_price_amount=Decimal("2000.00"),
        )
        return student, link

    def test_second_subject_uses_same_student_and_independent_lesson_terms(self):
        student, original = self._student_with_subject()
        subject = Subject.objects.create(name="Информатика", slug="second-subject")
        self.client.force_login(self.teacher)
        response = self.client.post(reverse("students:edit", args=[student.public_id]), {
            "action": "add_subject", "subject": subject.pk,
            "default_duration_minutes": "90", "default_price_amount": "2500", "currency": "RUB",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(StudentRecord.objects.count(), 1)
        second = TeacherStudentLink.objects.get(student_record=student, subject=subject)
        self.assertEqual(second.status, TeacherStudentLink.Status.ACTIVE)
        original.refresh_from_db()
        self.assertEqual(original.default_price_amount, Decimal("2000"))
        self.assertEqual(original.default_duration_minutes, 60)
        form = LessonCreateForm({
            "teacher_student_link": second.pk, "lesson_date": "2026-09-15",
            "local_time": "19:00", "timezone": "Europe/Moscow",
        }, teacher=self.teacher)
        self.assertTrue(form.is_valid(), form.errors)
        lesson = form.save()
        self.assertEqual(lesson.price_amount, Decimal("2500"))
        self.assertEqual(lesson.duration_minutes, 90)
        response = self.client.get(reverse("students:edit", args=[student.public_id]))
        self.assertContains(response, "Математика")
        self.assertContains(response, "Информатика")

    def test_duplicate_subject_is_rejected_without_overwriting_terms(self):
        student, original = self._student_with_subject()
        self.client.force_login(self.teacher)
        response = self.client.post(reverse("students:edit", args=[student.public_id]), {
            "action": "add_subject", "subject": self.subject.pk,
            "default_duration_minutes": "90", "default_price_amount": "2500", "currency": "RUB",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("subject", response.context["subject_form"].errors)
        self.assertEqual(TeacherStudentLink.objects.filter(student_record=student).count(), 1)
        original.refresh_from_db()
        self.assertEqual(original.default_price_amount, Decimal("2000"))

    def _defaults_data(self, link, **overrides):
        data = {
            "action": "edit_lesson_defaults", "link_id": str(link.pk),
            f"terms-{link.pk}-default_duration_minutes": "90",
            f"terms-{link.pk}-default_price_amount": "2500.00",
            f"terms-{link.pk}-currency": "rub",
        }
        data.update({f"terms-{link.pk}-{key}": value for key, value in overrides.items()})
        return data

    def test_edit_defaults_affects_new_lessons_only_and_selected_subject(self):
        student, link = self._student_with_subject()
        second = TeacherStudentLink.objects.create(
            teacher=self.teacher, student_record=student,
            subject=Subject.objects.create(name="Физика", slug="defaults-physics"),
            status=TeacherStudentLink.Status.ACTIVE, default_price_amount=1500,
        )
        existing = create_lesson(
            link=link, scheduled_start=datetime(2026, 9, 7, 16, tzinfo=datetime_timezone.utc),
            duration_minutes=60, price_amount=Decimal("2000"), created_by=self.teacher,
        )
        self.client.force_login(self.teacher)
        url = reverse("students:edit", args=[student.public_id])
        self.assertContains(self.client.get(url), f'terms-{link.pk}-default_price_amount')
        response = self.client.post(url, self._defaults_data(link))
        self.assertEqual(response.status_code, 302)
        link.refresh_from_db()
        second.refresh_from_db()
        existing.refresh_from_db()
        self.assertEqual((link.default_duration_minutes, link.default_price_amount, link.currency),
                         (90, Decimal("2500"), "RUB"))
        self.assertEqual((second.default_duration_minutes, second.default_price_amount), (60, Decimal("1500")))
        self.assertEqual((existing.duration_minutes, existing.price_amount), (60, Decimal("2000")))
        form = LessonCreateForm({
            "teacher_student_link": link.pk, "lesson_date": "2026-10-15",
            "local_time": "19:00", "timezone": "Europe/Moscow",
        }, teacher=self.teacher)
        self.assertTrue(form.is_valid(), form.errors)
        lesson = form.save()
        self.assertEqual((lesson.duration_minutes, lesson.price_amount), (90, Decimal("2500")))

    def test_invalid_defaults_display_errors_without_saving(self):
        student, link = self._student_with_subject()
        self.client.force_login(self.teacher)
        response = self.client.post(reverse("students:edit", args=[student.public_id]),
                                   self._defaults_data(link, default_duration_minutes="0",
                                                       default_price_amount="-1", currency="123"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["subject_links"][0].defaults_form.errors), 3)
        link.refresh_from_db()
        self.assertEqual((link.default_duration_minutes, link.default_price_amount), (60, Decimal("2000")))

    def test_cannot_edit_other_teachers_or_other_students_defaults(self):
        student, link = self._student_with_subject()
        other_teacher = get_user_model().objects.create_user(username="defaults-other")
        foreign_link = TeacherStudentLink.objects.create(
            teacher=other_teacher, student_record=student, subject=self.subject,
        )
        other_student = StudentRecord.objects.create(full_name="Другой ученик")
        other_link = TeacherStudentLink.objects.create(
            teacher=self.teacher, student_record=other_student, subject=self.subject,
        )
        self.client.force_login(self.teacher)
        for target in (foreign_link, other_link):
            response = self.client.post(reverse("students:edit", args=[student.public_id]),
                                       self._defaults_data(target))
            self.assertEqual(response.status_code, 403)
            target.refresh_from_db()
            self.assertEqual(target.default_price_amount, Decimal("0"))

    def test_outsider_cannot_add_subject_to_student(self):
        student, _ = self._student_with_subject()
        subject = Subject.objects.create(name="Физика", slug="outsider-subject")
        outsider = get_user_model().objects.create_user(username="subject-outsider")
        self.client.force_login(outsider)
        response = self.client.post(reverse("students:edit", args=[student.public_id]), {
            "action": "add_subject", "subject": subject.pk,
            "default_duration_minutes": "60", "default_price_amount": "1000", "currency": "RUB",
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(TeacherStudentLink.objects.filter(subject=subject).exists())

    def test_editing_student_card_still_works_with_separate_subject_form(self):
        student, _ = self._student_with_subject()
        self.client.force_login(self.teacher)
        response = self.client.post(reverse("students:edit", args=[student.public_id]), {
            "action": "edit_student", "full_name": "Анна Петрова",
            "status": "active", "timezone": "Europe/Moscow", "grade": "10",
        })
        self.assertEqual(response.status_code, 302)
        student.refresh_from_db()
        self.assertEqual(student.full_name, "Анна Петрова")
        self.assertEqual(TeacherStudentLink.objects.filter(student_record=student).count(), 1)

    def test_student_list_defaults_to_active_students_and_all_includes_paused(self):
        active, _ = self._student_with_subject()
        active.status = StudentRecord.Status.ACTIVE
        active.save()
        paused = StudentRecord.objects.create(full_name="Ученик на паузе", status=StudentRecord.Status.PAUSED)
        TeacherStudentLink.objects.create(teacher=self.teacher, student_record=paused,
                                         subject=self.subject, status=TeacherStudentLink.Status.ACTIVE)
        self.client.force_login(self.teacher)
        url = reverse("accounts:dashboard-students")
        response = self.client.get(url)
        self.assertContains(response, active.full_name)
        self.assertNotContains(response, paused.full_name)
        response = self.client.get(url, {"students": "all"})
        self.assertContains(response, active.full_name)
        self.assertContains(response, paused.full_name)
        self.assertEqual(StudentRecord.objects.get(pk=paused.pk).status, StudentRecord.Status.PAUSED)

    def test_active_filter_excludes_revoked_subjects_and_all_remains_teacher_scoped(self):
        student, link = self._student_with_subject()
        student.status = StudentRecord.Status.ACTIVE
        student.save()
        link.status = TeacherStudentLink.Status.REVOKED
        link.save()
        other_teacher = get_user_model().objects.create_user(username="other-list-teacher")
        other = StudentRecord.objects.create(full_name="Другой преподаватель ученик", status=StudentRecord.Status.ACTIVE)
        TeacherStudentLink.objects.create(teacher=other_teacher, student_record=other,
                                         subject=self.subject, status=TeacherStudentLink.Status.ACTIVE)
        self.client.force_login(self.teacher)
        url = reverse("accounts:dashboard-students")
        self.assertNotContains(self.client.get(url), student.full_name)
        response = self.client.get(url, {"students": "all"})
        self.assertContains(response, student.full_name)
        self.assertNotContains(response, other.full_name)
        self.assertEqual(self.client.get(url, {"students": "unknown"}).context["student_filter"], "active")
