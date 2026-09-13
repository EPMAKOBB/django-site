from datetime import date, datetime, time, timedelta, timezone as utc
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import TeacherProfile, TeacherStudentLink
from lessons.models import Lesson, LessonEvent, LessonPayment, LessonRescheduleRequest
from lessons.services import (
    cancel_lesson, complete_lesson, create_lesson, create_series,
    record_payment, request_reschedule, reschedule_lesson, update_series,
)
from students.models import StudentRecord
from subjects.models import Subject


class SeriesMoveTests(TestCase):
    def setUp(self):
        clock = patch("django.utils.timezone.now", return_value=datetime(2026, 9, 7, 8, tzinfo=utc.utc))
        clock.start()
        self.addCleanup(clock.stop)
        self.teacher = get_user_model().objects.create_user(username="series-move-teacher")
        TeacherProfile.objects.create(user=self.teacher)
        self.link = TeacherStudentLink.objects.create(
            teacher=self.teacher, student_record=StudentRecord.objects.create(full_name="Ученик"),
            subject=Subject.objects.create(name="Математика", slug="series-move-math"), status="active",
        )
        self.series, _ = create_series(
            link=self.link, weekdays=[1, 3], local_time=time(19), timezone_name="Europe/Moscow",
            start_date=date(2026, 9, 1), end_date=date(2026, 9, 30), duration_minutes=60,
            price_amount=Decimal("2000"), created_by=self.teacher,
        )

    def edit(self, **changes):
        arguments = dict(
            series=self.series, link=self.link, weekdays=[0, 3], local_time=time(19),
            timezone_name="Europe/Moscow", start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30), duration_minutes=60,
            price_amount=Decimal("2000"), actor=self.teacher,
        )
        arguments.update(changes)
        return update_series(**arguments)

    def on_day(self, day):
        return self.series.lessons.get(scheduled_start=datetime(2026, 9, day, 16, tzinfo=utc.utc))

    def test_tuesday_moves_monday_but_thursday_payment_and_notes_stay_intact(self):
        tuesday = self.on_day(15)
        thursday = self.on_day(17)
        past = self.on_day(1)
        complete_lesson(lesson=past, actor=self.teacher)
        payment = record_payment(lesson=tuesday, actor=self.teacher)
        tuesday.teacher_notes = "Сохранить разбор задач"
        tuesday.save(update_fields=["teacher_notes"])
        unchanged = (thursday.scheduled_start, thursday.updated_at, thursday.payment.pk)
        existing_ids = set(self.series.lessons.values_list("pk", flat=True))
        # A pending request for Thursday must not be discarded by a Tuesday move.
        request = request_reschedule(lesson=thursday, requested_by=self.teacher,
                                     proposed_start=thursday.scheduled_start + timedelta(days=1))
        _, report = self.edit()
        tuesday.refresh_from_db()
        thursday.refresh_from_db()
        request.refresh_from_db()
        past.refresh_from_db()
        self.assertEqual(tuesday.scheduled_start, datetime(2026, 9, 14, 16, tzinfo=utc.utc))
        self.assertEqual(tuesday.teacher_notes, "Сохранить разбор задач")
        self.assertEqual(tuesday.payment.pk, payment.pk)
        self.assertEqual(tuesday.payment.status, LessonPayment.Status.PAID)
        self.assertEqual((thursday.scheduled_start, thursday.updated_at, thursday.payment.pk), unchanged)
        self.assertEqual(request.status, LessonRescheduleRequest.Status.PENDING)
        self.assertEqual(past.status, Lesson.Status.COMPLETED)
        self.assertEqual(past.scheduled_start, datetime(2026, 9, 1, 16, tzinfo=utc.utc))
        self.assertEqual(set(self.series.lessons.values_list("pk", flat=True)), existing_ids)
        self.assertEqual((report.moved_count, report.cancelled_count, report.generation.created_count), (4, 0, 0))
        self.assertEqual(tuesday.events.filter(event_type=LessonEvent.Type.RESCHEDULED).count(), 1)
        self.assertFalse(Lesson.objects.filter(status=Lesson.Status.CANCELLED).exists())

    def test_conflict_rolls_back_entire_series_and_keeps_pending_requests(self):
        tuesday = self.on_day(15)
        pending = request_reschedule(lesson=tuesday, requested_by=self.teacher,
                                     proposed_start=tuesday.scheduled_start + timedelta(days=1))
        create_lesson(link=self.link, scheduled_start=datetime(2026, 9, 14, 16, tzinfo=utc.utc),
                      duration_minutes=60, price_amount=Decimal("2000"), created_by=self.teacher)
        before = list(self.series.lessons.values_list("pk", "scheduled_start", "status"))
        events = LessonEvent.objects.count()
        with self.assertRaisesMessage(ValidationError, "занято"):
            self.edit()
        self.series.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual(self.series.weekdays, [1, 3])
        self.assertEqual(list(self.series.lessons.values_list("pk", "scheduled_start", "status")), before)
        self.assertEqual(pending.status, LessonRescheduleRequest.Status.PENDING)
        self.assertEqual(LessonEvent.objects.count(), events)

    def test_pending_request_for_moved_lesson_is_closed(self):
        lesson = self.on_day(15)
        pending = request_reschedule(lesson=lesson, requested_by=self.teacher,
                                     proposed_start=lesson.scheduled_start + timedelta(days=1))
        self.edit()
        pending.refresh_from_db()
        self.assertEqual(pending.status, LessonRescheduleRequest.Status.CANCELLED)

    def test_individual_exception_is_not_moved_or_recreated(self):
        lesson = self.on_day(15)
        exception = datetime(2026, 9, 16, 18, tzinfo=utc.utc)
        reschedule_lesson(lesson=lesson, actor=self.teacher, proposed_start=exception)
        count = self.series.lessons.count()
        self.edit()
        lesson.refresh_from_db()
        self.assertEqual(lesson.scheduled_start, exception)
        self.assertEqual(self.series.lessons.count(), count)
        self.assertFalse(self.series.lessons.filter(scheduled_start=datetime(2026, 9, 14, 16, tzinfo=utc.utc)).exists())

    def test_past_time_is_not_used_when_current_week_monday_already_passed(self):
        lesson = self.on_day(8)
        with patch("django.utils.timezone.now", return_value=datetime(2026, 9, 8, 8, tzinfo=utc.utc)):
            _, report = self.edit()
        lesson.refresh_from_db()
        self.assertEqual(lesson.scheduled_start, datetime(2026, 9, 8, 16, tzinfo=utc.utc))
        self.assertEqual(report.moved_count, 3)

    def test_new_day_adds_only_new_occurrences(self):
        before = set(self.series.lessons.values_list("pk", flat=True))
        _, report = self.edit(weekdays=[1, 3, 4])
        self.assertEqual(report.moved_count, 0)
        self.assertEqual(report.generation.created_count, 3)
        self.assertTrue(before.issubset(set(self.series.lessons.values_list("pk", flat=True))))

    def test_conflict_in_extended_period_rolls_back_preceding_moves(self):
        create_lesson(link=self.link, scheduled_start=datetime(2026, 10, 1, 16, tzinfo=utc.utc),
                      duration_minutes=60, price_amount=Decimal("2000"), created_by=self.teacher)
        before = list(self.series.lessons.values_list("pk", "scheduled_start"))
        events = LessonEvent.objects.count()
        with self.assertRaises(ValidationError):
            self.edit(end_date=date(2026, 10, 15))
        self.series.refresh_from_db()
        self.assertEqual(self.series.end_date, date(2026, 9, 30))
        self.assertEqual(self.series.weekdays, [1, 3])
        self.assertEqual(list(self.series.lessons.values_list("pk", "scheduled_start")), before)
        self.assertEqual(LessonEvent.objects.count(), events)

    def test_removing_paid_occurrence_is_rejected_but_moving_is_allowed(self):
        paid = self.on_day(15)
        record_payment(lesson=paid, actor=self.teacher)
        with self.assertRaisesMessage(ValidationError, "оплаченный"):
            self.edit(weekdays=[3])
        self.edit()
        paid.refresh_from_db()
        self.assertEqual(paid.payment.status, LessonPayment.Status.PAID)

    def test_legacy_rebuild_cancellations_hidden_in_calendar_but_kept_in_history(self):
        legacy = self.on_day(15)
        cancel_lesson(lesson=legacy, actor=self.teacher, reason="Расписание серии изменено")
        Lesson.objects.filter(pk=legacy.pk).update(series=None)
        real_cancellation = self.on_day(17)
        cancel_lesson(lesson=real_cancellation, actor=self.teacher, reason="Ученик заболел")
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("lessons:calendar-events"), {
            "start": "2026-09-01", "end": "2026-10-01",
        })
        ids = {event["id"] for event in response.json()}
        self.assertNotIn(str(legacy.pk), ids)
        self.assertIn(str(real_cancellation.pk), ids)
        response = self.client.get(reverse("lessons:schedule"))
        self.assertIn(legacy.pk, {row["lesson"].pk for row in response.context["history_rows"]})
