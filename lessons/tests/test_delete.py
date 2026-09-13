from datetime import date, datetime, time, timedelta, timezone as utc
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import TeacherProfile, TeacherStudentLink
from lessons.models import Lesson, LessonEvent, LessonRescheduleRequest
from lessons.services import (
    complete_lesson, create_series, delete_lesson, generate_series_occurrences,
    record_payment, reopen_lesson, request_reschedule,
)
from subjects.models import Subject


class DeleteLessonTests(TestCase):
    def setUp(self):
        clock = patch("django.utils.timezone.now", return_value=datetime(2026, 9, 1, tzinfo=utc.utc))
        clock.start()
        self.addCleanup(clock.stop)
        users = get_user_model()
        self.teacher = users.objects.create_user(username="delete-teacher")
        TeacherProfile.objects.create(user=self.teacher)
        self.student = users.objects.create_user(username="delete-student")
        link = TeacherStudentLink.objects.create(
            teacher=self.teacher, student=self.student,
            subject=Subject.objects.create(name="Математика", slug="delete-math"), status="active",
        )
        self.series, _ = create_series(
            link=link, weekdays=[0], local_time=time(19), timezone_name="Europe/Moscow",
            start_date=date(2026, 9, 7), end_date=date(2026, 9, 14), duration_minutes=60,
            price_amount=Decimal("2000"), created_by=self.teacher,
        )
        self.lesson, self.sibling = list(self.series.lessons.all())
        self.url = reverse("lessons:lesson-action", args=[self.lesson.pk])
        self.client.force_login(self.teacher)

    def test_delete_hides_lesson_preserves_audit_and_does_not_change_series(self):
        pending = request_reschedule(lesson=self.lesson, requested_by=self.student,
            proposed_start=self.lesson.scheduled_start + timedelta(days=1))
        response = self.client.post(self.url, {"action": "delete"})
        self.assertRedirects(response, reverse("lessons:schedule"))
        self.lesson.refresh_from_db()
        self.sibling.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual(self.lesson.status, Lesson.Status.DELETED)
        self.assertEqual(self.lesson.series_id, self.series.pk)
        self.assertEqual(self.sibling.status, Lesson.Status.SCHEDULED)
        self.assertEqual(pending.status, LessonRescheduleRequest.Status.CANCELLED)
        self.assertEqual(self.lesson.events.get(event_type=LessonEvent.Type.DELETED).actor, self.teacher)
        self.assertEqual(self.series.lessons.count(), 2)
        response = self.client.get(reverse("lessons:schedule"), {"month": "2026-09"})
        self.assertEqual(response.context["statistics"]["planned"], 1)
        self.assertEqual(response.context["payment_summary"]["unpaid_count"], 1)
        visible = response.context["upcoming_rows"] + response.context["history_rows"]
        self.assertNotIn(self.lesson.pk, [row["lesson"].pk for row in visible])
        events = self.client.get(reverse("lessons:calendar-events"), {
            "start": "2026-09-01", "end": "2026-10-01",
        }).json()
        self.assertEqual([event["id"] for event in events], [str(self.sibling.pk)])

    def test_completed_and_paid_lessons_are_protected(self):
        complete_lesson(lesson=self.lesson, actor=self.teacher)
        record_payment(lesson=self.sibling, actor=self.teacher)
        for lesson in (self.lesson, self.sibling):
            with self.subTest(lesson=lesson.pk):
                with self.assertRaises(ValidationError):
                    delete_lesson(lesson=lesson, actor=self.teacher)
                self.client.post(reverse("lessons:lesson-action", args=[lesson.pk]), {"action": "delete"})
                lesson.refresh_from_db()
                self.assertNotEqual(lesson.status, Lesson.Status.DELETED)
                self.assertFalse(lesson.events.filter(event_type=LessonEvent.Type.DELETED).exists())

    def test_student_and_outsider_cannot_delete_and_get_cannot_mutate(self):
        self.assertEqual(self.client.get(self.url, {"action": "delete"}).status_code, 405)
        outsider = get_user_model().objects.create_user(username="delete-outsider")
        for user in (self.student, outsider):
            self.client.force_login(user)
            self.client.post(self.url, {"action": "delete"})
            self.lesson.refresh_from_db()
            self.assertEqual(self.lesson.status, Lesson.Status.SCHEDULED)

    def test_deleted_series_occurrence_is_not_regenerated(self):
        delete_lesson(lesson=self.lesson, actor=self.teacher)
        self.series.generated_through = None
        self.series.save(update_fields=["generated_through"])
        report = generate_series_occurrences(self.series)
        self.assertEqual(report.created_count, 0)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, Lesson.Status.DELETED)
        self.assertEqual(self.series.lessons.count(), 2)

    def test_repeated_delete_is_idempotent_and_stale_actions_cannot_revive_lesson(self):
        delete_lesson(lesson=self.lesson, actor=self.teacher)
        delete_lesson(lesson=self.lesson, actor=self.teacher)
        self.assertEqual(self.lesson.events.filter(event_type=LessonEvent.Type.DELETED).count(), 1)
        for action in (record_payment, reopen_lesson, complete_lesson):
            with self.subTest(action=action.__name__):
                with self.assertRaises(ValidationError):
                    action(lesson=self.lesson, actor=self.teacher)
