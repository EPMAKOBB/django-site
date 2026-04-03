from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.recsys.middleware import RecsysDailyRefreshMiddleware
from apps.recsys.models import ExamVersion, Subject, TagMastery, TaskTag, TaskType, TypeMastery
from apps.recsys.services import refresh_student_recsys_state


class PeriodicRefreshTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create(username="daily-user")
        self.subject = Subject.objects.create(name="Math")
        self.exam_version = ExamVersion.objects.create(name="Exam", subject=self.subject)
        self.task_type = TaskType.objects.create(
            name="Type",
            subject=self.subject,
            exam_version=self.exam_version,
        )
        self.tag = TaskTag.objects.create(subject=self.subject, name="Tag")
        self.tag_mastery = TagMastery.objects.create(
            user=self.user,
            task_tag=self.tag,
            mastery=1.0,
            coverage=0.5,
            progress=0.5,
            confidence=0.6,
            stability=0.5,
            last_seen_at=timezone.now() - timedelta(days=10),
            last_success_at=timezone.now() - timedelta(days=10),
            attempts_total=5,
            successes_total=4,
        )
        self.type_mastery = TypeMastery.objects.create(
            user=self.user,
            task_type=self.task_type,
            mastery=0.2,
            coverage=0.2,
            progress=0.2,
            confidence=0.2,
            stability=0.2,
        )

    def test_refresh_student_recsys_state_applies_forgetting(self):
        result = refresh_student_recsys_state(self.user, now=timezone.now())

        self.tag_mastery.refresh_from_db()
        self.assertEqual(result["tag_forgetting"], 1)
        self.assertLess(self.tag_mastery.mastery, 1.0)

    def test_daily_refresh_middleware_runs_once_per_day(self):
        middleware = RecsysDailyRefreshMiddleware(lambda request: HttpResponse("ok"))
        factory = RequestFactory()

        request = factory.get("/")
        request.user = self.user
        middleware(request)
        self.tag_mastery.refresh_from_db()
        first_mastery = self.tag_mastery.mastery

        request_second = factory.get("/")
        request_second.user = self.user
        middleware(request_second)
        self.tag_mastery.refresh_from_db()

        self.assertEqual(self.tag_mastery.mastery, first_mastery)
