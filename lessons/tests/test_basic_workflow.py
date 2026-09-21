from datetime import datetime, timedelta, timezone as utc
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import TeacherProfile, TeacherStudentLink
from lessons.models import Lesson, LessonEvent, LessonPayment, LessonRescheduleRequest
from lessons.services import create_lesson, complete_lesson, record_payment
from students.models import StudentRecord
from subjects.models import Subject


class BasicLessonWorkflowTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 15, 10, tzinfo=utc.utc)
        clock = patch("django.utils.timezone.now", return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.teacher = get_user_model().objects.create_user(username="basic-teacher")
        TeacherProfile.objects.create(user=self.teacher)
        self.student = StudentRecord.objects.create(full_name="Ученик без аккаунта")
        self.link = TeacherStudentLink.objects.create(
            teacher=self.teacher, student_record=self.student,
            subject=Subject.objects.create(name="Физика", slug="basic-physics"),
            status=TeacherStudentLink.Status.ACTIVE,
        )
        self.client.force_login(self.teacher)

    def lesson(self, start=None, minutes=60):
        return create_lesson(link=self.link, scheduled_start=start or self.now,
                             duration_minutes=minutes, price_amount=Decimal("2000.00"),
                             created_by=self.teacher)

    def action(self, lesson, action):
        return self.client.post(reverse("lessons:lesson-action", args=[lesson.pk]), {"action": action})

    def test_teacher_can_plan_mark_and_correct_unregistered_student_lesson(self):
        self.client.post(reverse("lessons:lesson-create"), {
            "teacher_student_link": self.link.pk, "lesson_date": "2026-09-16",
            "local_time": "19:00", "timezone": "Europe/Moscow",
            "duration_minutes": "60", "price_amount": "2000",
        })
        lesson = Lesson.objects.get()
        self.action(lesson, "complete")
        self.action(lesson, "paid")
        lesson.refresh_from_db()
        self.assertEqual(lesson.status, Lesson.Status.COMPLETED)
        self.assertEqual(lesson.payment.status, LessonPayment.Status.PAID)
        self.action(lesson, "reopen")
        lesson.refresh_from_db()
        self.assertEqual(lesson.status, Lesson.Status.SCHEDULED)
        self.assertIsNone(lesson.completed_at)
        self.assertEqual(lesson.payment.status, LessonPayment.Status.PAID)
        self.action(lesson, "unpaid")
        lesson.payment.refresh_from_db()
        self.assertEqual(lesson.payment.status, LessonPayment.Status.UNPAID)
        self.assertIsNone(lesson.payment.paid_at)
        self.assertEqual(lesson.events.filter(event_type=LessonEvent.Type.PAYMENT_UNPAID).count(), 1)

    def test_repeated_marks_do_not_duplicate_events_or_move_payment_date(self):
        lesson = self.lesson()
        self.action(lesson, "complete")
        self.action(lesson, "paid")
        lesson.payment.refresh_from_db()
        paid_at = lesson.payment.paid_at
        with patch("django.utils.timezone.now", return_value=self.now + timedelta(days=40)):
            self.action(lesson, "complete")
            self.action(lesson, "paid")
        lesson.payment.refresh_from_db()
        self.assertEqual(lesson.payment.paid_at, paid_at)
        self.assertEqual(lesson.events.filter(event_type=LessonEvent.Type.PAYMENT_PAID).count(), 1)
        self.assertEqual(lesson.events.filter(event_type=LessonEvent.Type.COMPLETED).count(), 1)

    def test_teacher_reschedules_without_confirmation_and_keeps_payment(self):
        lesson = self.lesson()
        record_payment(lesson=lesson, actor=self.teacher)
        response = self.client.post(reverse("lessons:reschedule", args=[lesson.pk]), {
            "proposed_start": "2026-09-17T19:00", "reason": "Договорились лично",
        })
        self.assertRedirects(response, reverse("lessons:schedule"))
        lesson.refresh_from_db()
        self.assertEqual(lesson.scheduled_start, datetime(2026, 9, 17, 16, tzinfo=utc.utc))
        self.assertEqual(lesson.payment.status, LessonPayment.Status.PAID)
        self.assertFalse(LessonRescheduleRequest.objects.exists())

    def test_calendar_teacher_move_rejects_conflicts_then_moves_directly(self):
        lesson = self.lesson()
        other = self.lesson(self.now + timedelta(days=1))
        url = reverse("lessons:calendar-reschedule", args=[lesson.pk])
        response = self.client.post(url, {"proposed_start": "2026-09-16T13:00"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        lesson.refresh_from_db()
        self.assertEqual(lesson.scheduled_start, self.now)
        response = self.client.post(url, {"proposed_start": "2026-09-16T15:00"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["rescheduled"])
        other.refresh_from_db()
        self.assertEqual(other.scheduled_start, self.now + timedelta(days=1))

    def test_month_statistics_use_local_lesson_dates_and_actual_payment_dates(self):
        # September 1, 01:00 Moscow, despite the UTC date being August 31.
        first = self.lesson(datetime(2026, 8, 31, 22, tzinfo=utc.utc), minutes=75)
        complete_lesson(lesson=first, actor=self.teacher)
        second = self.lesson(self.now - timedelta(days=1))
        complete_lesson(lesson=second, actor=self.teacher)
        record_payment(lesson=second, actor=self.teacher)
        self.lesson(self.now + timedelta(days=1))  # Future unpaid lessons are not debt.
        response = self.client.get(reverse("lessons:schedule"), {"month": "2026-09"})
        stats = response.context["statistics"]
        self.assertEqual((stats["completed"], stats["planned"], stats["minutes"]), (2, 1, 135))
        self.assertEqual(stats["unpaid_completed"], 1)
        self.assertEqual(stats["debt_amounts"], [{"payment__currency": "RUB", "total": Decimal("2000")}])
        august = self.client.get(reverse("lessons:schedule"), {"month": "2026-08"})
        self.assertEqual(august.context["statistics"]["completed"], 0)
        self.assertEqual(august.context["payment_summary"]["paid_month_amounts"], [])
        self.assertEqual(response.context["payment_summary"]["paid_month_amounts"],
                         [{"payment__currency": "RUB", "total": Decimal("2000")}])

    def test_student_cannot_correct_teacher_marks(self):
        user = get_user_model().objects.create_user(username="basic-student")
        self.student.user = user
        self.student.save()
        lesson = self.lesson()
        complete_lesson(lesson=lesson, actor=self.teacher)
        record_payment(lesson=lesson, actor=self.teacher)
        self.client.force_login(user)
        self.action(lesson, "reopen")
        self.action(lesson, "unpaid")
        lesson.refresh_from_db()
        self.assertEqual(lesson.status, Lesson.Status.COMPLETED)
        self.assertEqual(lesson.payment.status, LessonPayment.Status.PAID)

    def test_invalid_month_falls_back_and_old_history_is_accessible(self):
        for day in range(1, 28):
            self.lesson(self.now - timedelta(days=day))
        response = self.client.get(reverse("lessons:schedule"), {"month": "invalid", "page": "2"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_month"], "2026-09")
        self.assertEqual(len(response.context["history_rows"]), 2)
