from datetime import datetime, time, timedelta, timezone as datetime_timezone
from io import StringIO
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command, CommandError
from django.test import TestCase

from accounts.models import TeacherStudentLink
from lessons.forms import LessonCreateForm, LessonSeriesCreateForm
from lessons.models import Lesson, LessonEvent, LessonPayment, LessonRescheduleRequest, LessonSeries
from lessons.services import (
    cancel_lesson, complete_lesson, create_lesson, create_series,
    generate_series_occurrences, mark_no_show, record_payment,
    request_reschedule, resolve_reschedule, set_series_status, update_series,
)
from subjects.models import Subject


class LessonLifecycleTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 1, 10, tzinfo=datetime_timezone.utc)
        clock = patch("django.utils.timezone.now", return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)
        users = get_user_model()
        self.teacher = users.objects.create_user(username="lifecycle-teacher")
        self.student = users.objects.create_user(username="lifecycle-student")
        self.link = TeacherStudentLink.objects.create(
            teacher=self.teacher, student=self.student,
            subject=Subject.objects.create(name="Математика", slug="lifecycle-math"),
            status=TeacherStudentLink.Status.ACTIVE,
            default_duration_minutes=90, default_price_amount=Decimal("3500.00"),
        )

    def lesson(self, days=1):
        return create_lesson(
            link=self.link, scheduled_start=self.now + timedelta(days=days),
            duration_minutes=60, price_amount=Decimal("2000.00"), created_by=self.teacher,
        )

    def series(self):
        day = (self.now + timedelta(days=6)).date()
        series, _ = create_series(
            link=self.link, weekdays=[day.weekday()], local_time=time(15),
            timezone_name="UTC", start_date=day, end_date=day + timedelta(days=7),
            duration_minutes=60, price_amount=Decimal("2000.00"), created_by=self.teacher,
        )
        return series

    def test_terminal_actions_close_pending_requests_and_cannot_be_rescheduled(self):
        for days, action in enumerate((cancel_lesson, complete_lesson, mark_no_show), start=1):
            with self.subTest(action=action.__name__):
                lesson = self.lesson(days)
                original = lesson.scheduled_start
                request = request_reschedule(
                    lesson=lesson, requested_by=self.student,
                    proposed_start=original + timedelta(hours=2),
                )
                action(lesson=lesson, actor=self.teacher)
                request.refresh_from_db()
                self.assertEqual(request.status, LessonRescheduleRequest.Status.CANCELLED)
                self.assertEqual(request.resolved_by, self.teacher)
                self.assertIsNotNone(request.resolved_at)
                with self.assertRaises(ValidationError):
                    resolve_reschedule(change_request=request, resolved_by=self.teacher, accept=True)
                lesson.refresh_from_db()
                self.assertEqual(lesson.scheduled_start, original)
                self.assertFalse(lesson.events.filter(event_type=LessonEvent.Type.RESCHEDULE_ACCEPTED).exists())

    def test_legacy_pending_request_cannot_move_closed_lesson(self):
        lesson = self.lesson()
        request = request_reschedule(
            lesson=lesson, requested_by=self.student,
            proposed_start=lesson.scheduled_start + timedelta(hours=2),
        )
        Lesson.objects.filter(pk=lesson.pk).update(status=Lesson.Status.CANCELLED)
        with self.assertRaisesMessage(ValidationError, "запланированный"):
            resolve_reschedule(change_request=request, resolved_by=self.teacher, accept=True)

    def test_stale_request_cannot_overwrite_new_lesson_time(self):
        lesson = self.lesson()
        request = request_reschedule(
            lesson=lesson, requested_by=self.student,
            proposed_start=lesson.scheduled_start + timedelta(hours=2),
        )
        new_start = lesson.scheduled_start + timedelta(hours=3)
        Lesson.objects.filter(pk=lesson.pk).update(scheduled_start=new_start)
        with self.assertRaisesMessage(ValidationError, "устарел"):
            resolve_reschedule(change_request=request, resolved_by=self.teacher, accept=True)
        lesson.refresh_from_db()
        self.assertEqual(lesson.scheduled_start, new_start)

    def test_fully_generated_future_series_stays_active_and_can_end(self):
        series = self.series()
        self.assertEqual(series.status, LessonSeries.Status.ACTIVE)
        self.assertEqual(series.generated_through, series.end_date)
        self.assertEqual(generate_series_occurrences(series).created_count, 0)
        series, count = set_series_status(series=series, actor=self.teacher, action="end")
        self.assertEqual(count, 2)
        self.assertEqual(series.status, LessonSeries.Status.ENDED)

    def test_elapsed_series_finishes_even_if_generation_is_already_complete(self):
        series = self.series()
        with patch("django.utils.timezone.now", return_value=self.now + timedelta(days=20)):
            self.assertEqual(generate_series_occurrences(series).created_count, 0)
        series.refresh_from_db()
        self.assertEqual(series.status, LessonSeries.Status.ENDED)

    def test_rescheduled_future_lesson_keeps_elapsed_series_active(self):
        series = self.series()
        lesson = series.lessons.last()
        request = request_reschedule(
            lesson=lesson, requested_by=self.student,
            proposed_start=self.now + timedelta(days=30),
        )
        resolve_reschedule(change_request=request, resolved_by=self.teacher, accept=True)
        with patch("django.utils.timezone.now", return_value=self.now + timedelta(days=20)):
            generate_series_occurrences(series)
        series.refresh_from_db()
        self.assertEqual(series.status, LessonSeries.Status.ACTIVE)

    def test_paid_series_time_change_keeps_lessons_and_payments(self):
        series = self.series()
        lesson = series.lessons.first()
        payment = record_payment(lesson=lesson, actor=self.teacher)
        before = list(series.lessons.values_list("pk", "scheduled_start", "status"))
        update_series(
                series=series, link=self.link, weekdays=series.weekdays,
                local_time=time(16), timezone_name=series.timezone,
                start_date=series.start_date, end_date=series.end_date,
                duration_minutes=60, price_amount=Decimal("2000.00"), actor=self.teacher,
            )
        self.assertEqual(list(series.lessons.values_list("pk", flat=True)), [row[0] for row in before])
        series.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(series.local_time, time(16))
        self.assertEqual(payment.status, LessonPayment.Status.PAID)
        self.assertEqual(payment.lesson_id, lesson.pk)

    def test_individual_reschedule_preserves_payment(self):
        lesson = self.lesson()
        payment = record_payment(lesson=lesson, actor=self.teacher)
        request = request_reschedule(
            lesson=lesson, requested_by=self.student,
            proposed_start=lesson.scheduled_start + timedelta(hours=2),
        )
        resolve_reschedule(change_request=request, resolved_by=self.teacher, accept=True)
        lesson.refresh_from_db()
        self.assertEqual(lesson.payment.pk, payment.pk)
        self.assertEqual(lesson.payment.status, LessonPayment.Status.PAID)

    def form_data(self):
        return {
            "teacher_student_link": self.link.pk, "lesson_date": "2026-09-07",
            "start_date": "2026-09-07", "end_date": "2026-09-07", "weekdays": ["0"],
            "local_time": "15:00", "timezone": "Europe/Moscow",
        }

    def test_both_create_forms_use_student_terms_without_javascript(self):
        for form_class in (LessonCreateForm, LessonSeriesCreateForm):
            with self.subTest(form=form_class.__name__):
                form = form_class(self.form_data(), teacher=self.teacher)
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["duration_minutes"], 90)
                self.assertEqual(form.cleaned_data["price_amount"], Decimal("3500.00"))

    def test_explicit_free_lesson_is_not_replaced_by_default_price(self):
        form = LessonCreateForm(
            {**self.form_data(), "price_amount": "0", "duration_minutes": "45"},
            teacher=self.teacher,
        )
        self.assertTrue(form.is_valid(), form.errors)
        lesson = form.save()
        self.assertEqual(lesson.price_amount, Decimal("0.00"))
        self.assertEqual(lesson.duration_minutes, 45)

    def test_invalid_values_and_timezone_are_form_errors(self):
        for form_class in (LessonCreateForm, LessonSeriesCreateForm):
            form = form_class(
                {**self.form_data(), "price_amount": "-1", "timezone": "Unknown/Zone"},
                teacher=self.teacher,
            )
            self.assertFalse(form.is_valid())
            self.assertIn("price_amount", form.errors)
            self.assertIn("timezone", form.errors)

    def test_options_expose_terms_for_the_selected_student(self):
        form = LessonCreateForm(teacher=self.teacher)
        html = str(form["teacher_student_link"])
        self.assertIn('data-duration="90"', html)
        self.assertIn('data-price="3500.00"', html)

    def test_generator_continues_after_invalid_series_and_returns_failure(self):
        invalid = self.series()
        self.link.status = TeacherStudentLink.Status.REVOKED
        self.link.save()
        other_student = get_user_model().objects.create_user(username="generator-student")
        other_link = TeacherStudentLink.objects.create(
            teacher=self.teacher, student=other_student, subject=self.link.subject,
            status=TeacherStudentLink.Status.ACTIVE,
        )
        valid, _ = create_series(
            link=other_link, weekdays=invalid.weekdays, local_time=time(18),
            timezone_name="UTC", start_date=invalid.start_date, end_date=invalid.end_date,
            duration_minutes=60, price_amount=Decimal("2000.00"),
            created_by=self.teacher, generate_now=False,
        )
        stdout, stderr = StringIO(), StringIO()
        with self.assertRaises(CommandError):
            call_command("generate_lesson_occurrences", stdout=stdout, stderr=stderr)
        self.assertEqual(valid.lessons.count(), 2)
        self.assertIn(f"Series {invalid.pk}", stderr.getvalue())
        self.assertIn("ошибок: 1", stdout.getvalue())

    def test_generator_reports_conflict_with_nonzero_exit(self):
        series = self.series()
        # A new series overlapping existing occurrences must report every conflict.
        create_series(
            link=self.link, weekdays=series.weekdays, local_time=series.local_time,
            timezone_name=series.timezone, start_date=series.start_date,
            end_date=series.end_date, duration_minutes=60,
            price_amount=Decimal("2000.00"), created_by=self.teacher, generate_now=False,
        )
        stdout = StringIO()
        with self.assertRaises(CommandError):
            call_command("generate_lesson_occurrences", stdout=stdout, stderr=StringIO())
        self.assertIn("конфликтов: 2", stdout.getvalue())
        self.assertEqual(Lesson.objects.count(), 2)

    def test_currency_follows_student_terms(self):
        self.link.currency = "EUR"
        self.link.save()
        form = LessonCreateForm(self.form_data(), teacher=self.teacher)
        self.assertTrue(form.is_valid(), form.errors)
        lesson = form.save()
        self.assertEqual(lesson.currency, "EUR")
        self.assertEqual(lesson.payment.currency, "EUR")

    def test_outdated_request_can_be_rejected_to_allow_new_request(self):
        lesson = self.lesson()
        request = request_reschedule(
            lesson=lesson, requested_by=self.student,
            proposed_start=lesson.scheduled_start + timedelta(hours=2),
        )
        Lesson.objects.filter(pk=lesson.pk).update(
            scheduled_start=lesson.scheduled_start + timedelta(hours=3)
        )
        resolve_reschedule(change_request=request, resolved_by=self.teacher, accept=False)
        request.refresh_from_db()
        self.assertEqual(request.status, LessonRescheduleRequest.Status.REJECTED)
        request_reschedule(
            lesson=lesson, requested_by=self.student,
            proposed_start=lesson.scheduled_start + timedelta(days=1),
        )
