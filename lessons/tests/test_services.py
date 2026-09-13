from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from accounts.models import TeacherProfile, TeacherStudentLink, UserPreferences
from lessons.models import Lesson, LessonEvent, LessonPayment, LessonRescheduleRequest, LessonSeries
from lessons.services import (
    complete_lesson,
    create_lesson,
    create_series,
    record_payment,
    request_reschedule,
    resolve_reschedule,
    set_series_status,
    update_series,
)
from subjects.models import Subject


class LessonServiceTests(TestCase):
    def setUp(self):
        clock = patch("django.utils.timezone.now", return_value=datetime(2026, 9, 6, tzinfo=datetime_timezone.utc))
        clock.start()
        self.addCleanup(clock.stop)
        user_model = get_user_model()
        self.teacher = user_model.objects.create_user(username="teacher", password="pass")
        TeacherProfile.objects.create(user=self.teacher)
        self.student = user_model.objects.create_user(username="student", password="pass")
        self.other_student = user_model.objects.create_user(username="other", password="pass")
        self.subject = Subject.objects.create(name="Информатика", slug="informatics")
        self.link = TeacherStudentLink.objects.create(
            teacher=self.teacher,
            student=self.student,
            subject=self.subject,
            status=TeacherStudentLink.Status.ACTIVE,
        )

    def test_user_preferences_are_created_with_user(self):
        preferences = UserPreferences.objects.get(user=self.student)
        self.assertEqual(preferences.timezone, "Europe/Moscow")

    def test_monday_and_thursday_series_generates_individual_lessons(self):
        series, report = create_series(
            link=self.link,
            weekdays=[0, 3],
            local_time=time(19, 0),
            timezone_name="Europe/Moscow",
            start_date=date(2026, 9, 7),
            end_date=date(2026, 9, 17),
            duration_minutes=60,
            price_amount=Decimal("2000.00"),
            created_by=self.teacher,
        )

        self.assertEqual(report.created_count, 4)
        self.assertEqual(len(report.conflicts), 0)
        starts = list(series.lessons.order_by("scheduled_start").values_list("scheduled_start", flat=True))
        self.assertEqual(
            starts,
            [
                datetime(2026, 9, 7, 16, 0, tzinfo=datetime_timezone.utc),
                datetime(2026, 9, 10, 16, 0, tzinfo=datetime_timezone.utc),
                datetime(2026, 9, 14, 16, 0, tzinfo=datetime_timezone.utc),
                datetime(2026, 9, 17, 16, 0, tzinfo=datetime_timezone.utc),
            ],
        )
        self.assertEqual(LessonPayment.objects.filter(lesson__series=series).count(), 4)
        self.assertTrue(
            all(
                payment.amount == Decimal("2000.00")
                for payment in LessonPayment.objects.filter(lesson__series=series)
            )
        )

    def test_generation_reports_conflict_and_keeps_other_occurrences(self):
        create_lesson(
            link=self.link,
            scheduled_start=datetime(2026, 9, 7, 16, 0, tzinfo=datetime_timezone.utc),
            duration_minutes=60,
            price_amount=Decimal("1000.00"),
            created_by=self.teacher,
        )
        series, report = create_series(
            link=self.link,
            weekdays=[0, 3],
            local_time=time(19, 0),
            timezone_name="Europe/Moscow",
            start_date=date(2026, 9, 7),
            end_date=date(2026, 9, 10),
            duration_minutes=60,
            price_amount=Decimal("2000.00"),
            created_by=self.teacher,
        )
        self.assertEqual(report.created_count, 1)
        self.assertEqual(len(report.conflicts), 1)
        self.assertEqual(series.lessons.count(), 1)

    def test_series_keeps_local_time_across_daylight_saving_change(self):
        series, report = create_series(
            link=self.link,
            weekdays=[0],
            local_time=time(19, 0),
            timezone_name="Europe/Berlin",
            start_date=date(2026, 10, 19),
            end_date=date(2026, 10, 26),
            duration_minutes=60,
            price_amount=Decimal("2000.00"),
            created_by=self.teacher,
        )
        self.assertEqual(report.created_count, 2)
        starts = list(series.lessons.order_by("scheduled_start").values_list("scheduled_start", flat=True))
        self.assertEqual(starts[0].hour, 17)
        self.assertEqual(starts[1].hour, 18)

    def test_nonexistent_dst_time_is_reported_as_conflict(self):
        series, report = create_series(
            link=self.link,
            weekdays=[6],
            local_time=time(2, 30),
            timezone_name="Europe/Berlin",
            start_date=date(2026, 3, 29),
            end_date=date(2026, 3, 29),
            duration_minutes=60,
            price_amount=Decimal("2000.00"),
            created_by=self.teacher,
        )
        self.assertEqual(report.created_count, 0)
        self.assertEqual(len(report.conflicts), 1)
        self.assertEqual(series.lessons.count(), 0)

    def test_student_requests_and_teacher_accepts_reschedule(self):
        lesson = create_lesson(
            link=self.link,
            scheduled_start=datetime(2026, 9, 7, 16, 0, tzinfo=datetime_timezone.utc),
            duration_minutes=60,
            price_amount=Decimal("2000.00"),
            created_by=self.teacher,
        )
        proposed = lesson.scheduled_start + timedelta(days=1)
        change_request = request_reschedule(
            lesson=lesson,
            requested_by=self.student,
            proposed_start=proposed,
            reason="Экзамен",
        )
        resolve_reschedule(change_request=change_request, resolved_by=self.teacher, accept=True)

        lesson.refresh_from_db()
        change_request.refresh_from_db()
        self.assertEqual(lesson.scheduled_start, proposed)
        self.assertEqual(change_request.status, LessonRescheduleRequest.Status.ACCEPTED)

    def test_requester_cannot_accept_own_reschedule(self):
        lesson = create_lesson(
            link=self.link,
            scheduled_start=datetime(2026, 9, 7, 16, 0, tzinfo=datetime_timezone.utc),
            duration_minutes=60,
            price_amount=Decimal("2000.00"),
            created_by=self.teacher,
        )
        change_request = request_reschedule(
            lesson=lesson,
            requested_by=self.student,
            proposed_start=lesson.scheduled_start + timedelta(days=1),
        )
        with self.assertRaises(PermissionDenied):
            resolve_reschedule(change_request=change_request, resolved_by=self.student, accept=True)

    def test_teacher_completes_lesson_and_records_payment(self):
        lesson = create_lesson(
            link=self.link,
            scheduled_start=datetime(2026, 9, 7, 16, 0, tzinfo=datetime_timezone.utc),
            duration_minutes=60,
            price_amount=Decimal("2000.00"),
            created_by=self.teacher,
        )
        complete_lesson(lesson=lesson, actor=self.teacher, notes="Разобрали графы")
        payment = record_payment(
            lesson=lesson,
            actor=self.teacher,
            method=LessonPayment.Method.BANK_TRANSFER,
        )

        lesson.refresh_from_db()
        self.assertEqual(lesson.status, Lesson.Status.COMPLETED)
        self.assertEqual(lesson.teacher_notes, "Разобрали графы")
        self.assertEqual(payment.status, LessonPayment.Status.PAID)
        self.assertIsNotNone(payment.paid_at)
        self.assertTrue(
            LessonEvent.objects.filter(
                lesson=lesson,
                event_type=LessonEvent.Type.PAYMENT_PAID,
            ).exists()
        )

    def test_overlapping_lesson_is_rejected(self):
        first = create_lesson(
            link=self.link,
            scheduled_start=datetime(2026, 9, 7, 16, 0, tzinfo=datetime_timezone.utc),
            duration_minutes=60,
            price_amount=Decimal("2000.00"),
            created_by=self.teacher,
        )
        with self.assertRaises(ValidationError):
            create_lesson(
                link=self.link,
                scheduled_start=first.scheduled_start + timedelta(minutes=30),
                duration_minutes=60,
                price_amount=Decimal("2000.00"),
                created_by=self.teacher,
            )

    def test_series_student_change_updates_future_lessons_and_unpaid_amounts(self):
        other_link = TeacherStudentLink.objects.create(
            teacher=self.teacher,
            student=self.other_student,
            subject=self.subject,
            status=TeacherStudentLink.Status.ACTIVE,
        )
        series, _ = create_series(
            link=self.link,
            weekdays=[0, 3],
            local_time=time(19, 0),
            timezone_name="Europe/Moscow",
            start_date=date(2026, 9, 7),
            end_date=date(2026, 9, 17),
            duration_minutes=60,
            price_amount=Decimal("2000.00"),
            created_by=self.teacher,
        )

        series, report = update_series(
            series=series,
            link=other_link,
            weekdays=[0, 3],
            local_time=time(19, 0),
            timezone_name="Europe/Moscow",
            start_date=date(2026, 9, 7),
            end_date=date(2026, 9, 17),
            duration_minutes=90,
            price_amount=Decimal("2500.00"),
            actor=self.teacher,
        )

        self.assertEqual(report.updated_count, 4)
        self.assertEqual(series.teacher_student_link, other_link)
        self.assertFalse(series.lessons.exclude(teacher_student_link=other_link).exists())
        self.assertFalse(series.lessons.exclude(duration_minutes=90).exists())
        self.assertFalse(
            LessonPayment.objects.filter(lesson__series=series)
            .exclude(amount=Decimal("2500.00"))
            .exists()
        )

    def test_series_time_change_moves_existing_future_lessons(self):
        series, _ = create_series(
            link=self.link,
            weekdays=[0],
            local_time=time(19, 0),
            timezone_name="Europe/Moscow",
            start_date=date(2026, 9, 7),
            end_date=date(2026, 9, 14),
            duration_minutes=60,
            price_amount=Decimal("2000.00"),
            created_by=self.teacher,
        )
        old_ids = list(series.lessons.values_list("id", flat=True))

        series, report = update_series(
            series=series,
            link=self.link,
            weekdays=[0],
            local_time=time(20, 0),
            timezone_name="Europe/Moscow",
            start_date=date(2026, 9, 7),
            end_date=date(2026, 9, 14),
            duration_minutes=60,
            price_amount=Decimal("2000.00"),
            actor=self.teacher,
        )

        self.assertEqual(report.cancelled_count, 0)
        self.assertEqual(report.moved_count, 2)
        self.assertEqual(report.generation.created_count, 0)
        self.assertEqual(
            set(Lesson.objects.filter(id__in=old_ids).values_list("status", flat=True)),
            {Lesson.Status.SCHEDULED},
        )
        self.assertEqual(
            list(series.lessons.order_by("scheduled_start").values_list("scheduled_start__hour", flat=True)),
            [17, 17],
        )

    def test_ending_series_cancels_future_lessons(self):
        series, _ = create_series(
            link=self.link,
            weekdays=[0],
            local_time=time(19, 0),
            timezone_name="Europe/Moscow",
            start_date=date(2026, 9, 7),
            end_date=date(2026, 9, 14),
            duration_minutes=60,
            price_amount=Decimal("2000.00"),
            created_by=self.teacher,
        )

        series, cancelled_count = set_series_status(
            series=series,
            actor=self.teacher,
            action="end",
        )

        self.assertEqual(series.status, LessonSeries.Status.ENDED)
        self.assertEqual(cancelled_count, 2)
        self.assertFalse(series.lessons.filter(status=Lesson.Status.SCHEDULED).exists())
