import json
from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import TeacherProfile, TeacherStudentLink
from lessons.models import Lesson, LessonPayment, LessonRescheduleRequest, LessonSeries
from lessons.services import create_lesson, create_series
from subjects.models import Subject


class LessonViewsTests(TestCase):
    def setUp(self):
        clock = patch("django.utils.timezone.now", return_value=datetime(2026, 9, 6, tzinfo=datetime_timezone.utc))
        clock.start()
        self.addCleanup(clock.stop)
        user_model = get_user_model()
        self.teacher = user_model.objects.create_user(username="teacher-web", password="pass")
        TeacherProfile.objects.create(user=self.teacher)
        self.student = user_model.objects.create_user(username="student-web", password="pass")
        self.outsider = user_model.objects.create_user(username="outsider-web", password="pass")
        self.subject = Subject.objects.create(name="Математика", slug="math-web")
        self.link = TeacherStudentLink.objects.create(
            teacher=self.teacher,
            student=self.student,
            subject=self.subject,
            status=TeacherStudentLink.Status.ACTIVE,
        )

    def _lesson(self):
        return create_lesson(
            link=self.link,
            scheduled_start=datetime(2026, 9, 7, 16, 0, tzinfo=datetime_timezone.utc),
            duration_minutes=60,
            price_amount=Decimal("2000.00"),
            created_by=self.teacher,
        )

    def test_teacher_creates_monday_thursday_schedule(self):
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse("lessons:series-create"),
            {
                "teacher_student_link": self.link.id,
                "weekdays": ["0", "3"],
                "local_time": "19:00",
                "timezone": "Europe/Moscow",
                "start_date": "2026-09-07",
                "end_date": "2026-09-17",
                "duration_minutes": "60",
                "price_amount": "2000.00",
            },
        )
        self.assertRedirects(response, reverse("lessons:schedule"))
        self.assertEqual(Lesson.objects.count(), 4)
        self.assertEqual(LessonPayment.objects.count(), 4)

    def test_student_sees_local_and_moscow_time_when_they_differ(self):
        self._lesson()
        preferences = self.student.preferences
        preferences.timezone = "Asia/Yekaterinburg"
        preferences.timezone_confirmed = True
        preferences.save()
        self.client.force_login(self.student)

        response = self.client.get(reverse("lessons:schedule"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "07.09.2026 21:00")
        self.assertContains(response, "По Москве: 07.09.2026 19:00")

    def test_student_requests_and_teacher_accepts_reschedule_from_web(self):
        lesson = self._lesson()
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("lessons:reschedule", args=[lesson.id]),
            {
                "proposed_start": "2026-09-08T19:00",
                "reason": "Школьное мероприятие",
            },
        )
        self.assertRedirects(response, reverse("lessons:schedule"))
        change_request = LessonRescheduleRequest.objects.get(lesson=lesson)

        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse("lessons:reschedule-resolve", args=[change_request.id]),
            {"decision": "accept"},
        )
        self.assertRedirects(response, reverse("lessons:schedule"))
        lesson.refresh_from_db()
        self.assertEqual(
            lesson.scheduled_start,
            datetime(2026, 9, 8, 16, 0, tzinfo=datetime_timezone.utc),
        )

    def test_teacher_marks_lesson_completed_and_paid(self):
        lesson = self._lesson()
        self.client.force_login(self.teacher)
        self.client.post(
            reverse("lessons:lesson-action", args=[lesson.id]),
            {"action": "complete", "notes": "Разобрали квадратные уравнения"},
        )
        self.client.post(
            reverse("lessons:lesson-action", args=[lesson.id]),
            {"action": "paid"},
        )
        lesson.refresh_from_db()
        lesson.payment.refresh_from_db()
        self.assertEqual(lesson.status, Lesson.Status.COMPLETED)
        self.assertEqual(lesson.payment.status, LessonPayment.Status.PAID)

    def test_outsider_cannot_open_reschedule_page(self):
        lesson = self._lesson()
        self.client.force_login(self.outsider)
        response = self.client.get(reverse("lessons:reschedule", args=[lesson.id]))
        self.assertEqual(response.status_code, 404)

    def test_user_updates_timezone(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("lessons:timezone-settings"),
            {"city": "Екатеринбург", "timezone": "Asia/Yekaterinburg"},
        )
        self.assertRedirects(response, reverse("lessons:schedule"))
        self.student.preferences.refresh_from_db()
        self.assertEqual(self.student.preferences.city, "Екатеринбург")
        self.assertEqual(self.student.preferences.timezone, "Asia/Yekaterinburg")
        self.assertTrue(self.student.preferences.timezone_confirmed)

    def test_schedule_page_contains_calendar_views_and_events_url(self):
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("lessons:schedule"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="lesson-calendar"')
        self.assertContains(response, reverse("lessons:calendar-events"))
        self.assertContains(response, "fullcalendar@6.1.19")
        self.assertContains(response, "lesson-calendar.js")

    def test_calendar_events_use_viewer_timezone_and_include_details(self):
        lesson = self._lesson()
        preferences = self.student.preferences
        preferences.timezone = "Asia/Yekaterinburg"
        preferences.save(update_fields=["timezone"])
        self.client.force_login(self.student)

        response = self.client.get(
            reverse("lessons:calendar-events"),
            {"start": "2026-09-01T00:00:00+02:00", "end": "2026-10-01T00:00:00+02:00"},
        )

        self.assertEqual(response.status_code, 200)
        events = response.json()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["id"], str(lesson.id))
        self.assertEqual(events[0]["start"], "2026-09-07T21:00:00")
        self.assertEqual(events[0]["end"], "2026-09-07T22:00:00")
        self.assertEqual(events[0]["extendedProps"]["timezone"], "Asia/Yekaterinburg")
        self.assertEqual(events[0]["extendedProps"]["paymentStatus"], "unpaid")
        self.assertTrue(events[0]["extendedProps"]["canReschedule"])
        self.assertTrue(events[0]["editable"])

    def test_calendar_events_are_limited_to_visible_user(self):
        self._lesson()
        self.client.force_login(self.outsider)

        response = self.client.get(
            reverse("lessons:calendar-events"),
            {"start": "2026-09-01", "end": "2026-10-01"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_calendar_events_reject_invalid_or_excessive_range(self):
        self.client.force_login(self.teacher)

        missing_range = self.client.get(reverse("lessons:calendar-events"))
        excessive_range = self.client.get(
            reverse("lessons:calendar-events"),
            {"start": "2026-01-01", "end": "2028-01-01"},
        )

        self.assertEqual(missing_range.status_code, 400)
        self.assertEqual(excessive_range.status_code, 400)

    def test_calendar_drag_creates_reschedule_request_in_profile_timezone(self):
        lesson = self._lesson()
        preferences = self.student.preferences
        preferences.timezone = "Asia/Yekaterinburg"
        preferences.save(update_fields=["timezone"])
        self.client.force_login(self.student)

        response = self.client.post(
            reverse("lessons:calendar-reschedule", args=[lesson.id]),
            data=json.dumps({"proposed_start": "2026-09-08T19:30:00"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        change_request = LessonRescheduleRequest.objects.get(lesson=lesson)
        self.assertEqual(
            change_request.proposed_start,
            datetime(2026, 9, 8, 14, 30, tzinfo=datetime_timezone.utc),
        )

    def test_teacher_creates_one_off_lesson(self):
        self.client.force_login(self.teacher)

        response = self.client.post(
            reverse("lessons:lesson-create"),
            {
                "teacher_student_link": self.link.id,
                "lesson_date": "2026-09-09",
                "local_time": "18:00",
                "timezone": "Europe/Moscow",
                "duration_minutes": "90",
                "price_amount": "2300.00",
            },
        )

        self.assertRedirects(response, reverse("lessons:schedule"))
        lesson = Lesson.objects.get()
        self.assertIsNone(lesson.series_id)
        self.assertEqual(
            lesson.scheduled_start,
            datetime(2026, 9, 9, 15, 0, tzinfo=datetime_timezone.utc),
        )
        self.assertEqual(lesson.duration_minutes, 90)

    def test_teacher_changes_student_for_whole_future_series_from_web(self):
        user_model = get_user_model()
        other_student = user_model.objects.create_user(username="other-student-web", password="pass")
        other_link = TeacherStudentLink.objects.create(
            teacher=self.teacher,
            student=other_student,
            subject=self.subject,
            status=TeacherStudentLink.Status.ACTIVE,
        )
        series, _ = create_series(
            link=self.link,
            weekdays=[0, 3],
            local_time=datetime.strptime("19:00", "%H:%M").time(),
            timezone_name="Europe/Moscow",
            start_date=datetime.strptime("2026-09-07", "%Y-%m-%d").date(),
            end_date=datetime.strptime("2026-09-17", "%Y-%m-%d").date(),
            duration_minutes=60,
            price_amount=Decimal("2000.00"),
            created_by=self.teacher,
        )
        self.client.force_login(self.teacher)

        response = self.client.post(
            reverse("lessons:series-edit", args=[series.id]),
            {
                "teacher_student_link": other_link.id,
                "weekdays": ["0", "3"],
                "local_time": "19:00",
                "timezone": "Europe/Moscow",
                "start_date": "2026-09-07",
                "end_date": "2026-09-17",
                "duration_minutes": "60",
                "price_amount": "2000.00",
            },
        )

        self.assertRedirects(response, reverse("lessons:schedule"))
        series.refresh_from_db()
        self.assertEqual(series.teacher_student_link, other_link)
        self.assertFalse(series.lessons.exclude(teacher_student_link=other_link).exists())

    def test_teacher_can_end_series_from_web(self):
        series, _ = create_series(
            link=self.link,
            weekdays=[0],
            local_time=datetime.strptime("19:00", "%H:%M").time(),
            timezone_name="Europe/Moscow",
            start_date=datetime.strptime("2026-09-07", "%Y-%m-%d").date(),
            end_date=datetime.strptime("2026-09-14", "%Y-%m-%d").date(),
            duration_minutes=60,
            price_amount=Decimal("2000.00"),
            created_by=self.teacher,
        )
        self.client.force_login(self.teacher)

        response = self.client.post(
            reverse("lessons:series-action", args=[series.id]),
            {"action": "end"},
        )

        self.assertRedirects(response, reverse("lessons:schedule"))
        series.refresh_from_db()
        self.assertEqual(series.status, LessonSeries.Status.ENDED)

    def test_schedule_shows_payment_summary(self):
        lesson = self._lesson()
        self.client.force_login(self.teacher)

        unpaid_response = self.client.get(reverse("lessons:schedule"))
        self.assertEqual(unpaid_response.context["payment_summary"]["unpaid_count"], 1)
        self.assertEqual(
            unpaid_response.context["payment_summary"]["unpaid_amounts"],
            [{"payment__currency": "RUB", "total": Decimal("2000.00")}],
        )

        self.client.post(
            reverse("lessons:lesson-action", args=[lesson.id]),
            {"action": "paid"},
        )
        paid_response = self.client.get(reverse("lessons:schedule"))
        self.assertEqual(paid_response.context["payment_summary"]["unpaid_count"], 0)
        self.assertEqual(
            paid_response.context["payment_summary"]["paid_month_amounts"],
            [{"payment__currency": "RUB", "total": Decimal("2000.00")}],
        )

    def test_payment_summary_keeps_currencies_separate(self):
        self._lesson()
        create_lesson(
            link=self.link,
            scheduled_start=datetime(2026, 9, 8, 16, tzinfo=datetime_timezone.utc),
            duration_minutes=60, price_amount=Decimal("30.00"), currency="EUR",
            created_by=self.teacher,
        )
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("lessons:schedule"))
        self.assertEqual(response.context["payment_summary"]["unpaid_amounts"], [
            {"payment__currency": "EUR", "total": Decimal("30.00")},
            {"payment__currency": "RUB", "total": Decimal("2000.00")},
        ])

    def test_teacher_can_enter_notes_and_cancellation_reason_from_lesson_card(self):
        lesson = self._lesson()
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("lessons:schedule"))
        self.assertContains(response, 'name="notes"')
        self.assertContains(response, 'name="reason"')
        self.client.post(reverse("lessons:lesson-action", args=[lesson.pk]), {
            "action": "cancel", "reason": "Занятие отменено по договорённости",
        })
        response = self.client.get(reverse("lessons:schedule"))
        self.assertContains(response, "Занятие отменено по договорённости")
