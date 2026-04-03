from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.recsys.models import (
    Attempt,
    Subject,
    ExamVersion,
    Skill,
    TaskType,
    Task,
    TaskSkill,
    SkillMastery,
    RecommendationLog,
    TagMastery,
    TaskTag,
)
from apps.recsys.recommendation import (
    mark_recommendation_opened,
    recommend_task_candidates,
    recommend_tasks,
)


class RecommendationOrderTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="user")
        self.subject = Subject.objects.create(name="Subject")
        self.exam_version = ExamVersion.objects.create(name="V1", subject=self.subject)
        self.skill1 = Skill.objects.create(name="A", subject=self.subject)
        self.skill2 = Skill.objects.create(name="B", subject=self.subject)
        ttype = TaskType.objects.create(name="T", subject=self.subject)
        self.task1 = Task.objects.create(
            type=ttype, title="Task1", subject=self.subject, exam_version=self.exam_version
        )
        self.task2 = Task.objects.create(
            type=ttype, title="Task2", subject=self.subject, exam_version=self.exam_version
        )
        TaskSkill.objects.create(task=self.task1, skill=self.skill1, weight=1.0)
        TaskSkill.objects.create(task=self.task2, skill=self.skill2, weight=1.0)
        SkillMastery.objects.create(user=self.user, skill=self.skill1, mastery=0.8, confidence=1)
        SkillMastery.objects.create(user=self.user, skill=self.skill2, mastery=0.2, confidence=1)

    def test_order_lowest_mastery_first(self):
        tasks = recommend_tasks(self.user)
        self.assertEqual([t.title for t in tasks], ["Task2", "Task1"])
        for task in tasks:
            self.assertEqual(task.subject, self.subject)
            self.assertEqual(task.exam_version, self.exam_version)

    def test_mvp_prefers_weaker_tag_gap(self):
        weak_tag = TaskTag.objects.create(subject=self.subject, name="Weak tag")
        strong_tag = TaskTag.objects.create(subject=self.subject, name="Strong tag")

        weak_task = Task.objects.create(
            type=self.task1.type,
            title="WeakTask",
            subject=self.subject,
            exam_version=self.exam_version,
            difficulty_level=30,
            priority_manual=1.0,
        )
        strong_task = Task.objects.create(
            type=self.task1.type,
            title="StrongTask",
            subject=self.subject,
            exam_version=self.exam_version,
            difficulty_level=30,
            priority_manual=1.0,
        )
        weak_task.tags.add(weak_tag)
        strong_task.tags.add(strong_tag)

        TagMastery.objects.create(
            user=self.user,
            task_tag=weak_tag,
            mastery=0.2,
            coverage=0.2,
            progress=0.2,
            confidence=0.8,
            stability=0.2,
            last_seen_at=timezone.now() - timedelta(days=5),
            last_success_at=timezone.now() - timedelta(days=5),
            attempts_total=3,
            successes_total=1,
        )
        TagMastery.objects.create(
            user=self.user,
            task_tag=strong_tag,
            mastery=0.8,
            coverage=0.8,
            progress=0.8,
            confidence=0.8,
            stability=0.8,
            last_seen_at=timezone.now() - timedelta(days=1),
            last_success_at=timezone.now() - timedelta(days=1),
            attempts_total=3,
            successes_total=3,
        )

        tasks = recommend_tasks(self.user)
        titles = [task.title for task in tasks]
        self.assertLess(titles.index("WeakTask"), titles.index("StrongTask"))

    def test_recommend_tasks_filters_and_logs(self):
        RecommendationLog.objects.create(
            user=self.user,
            task=self.task1,
            recommended_at=timezone.now(),
            status=RecommendationLog.Status.RECOMMENDED,
            source_mode=RecommendationLog.SourceMode.TRAINING,
            rank_position=1,
        )
        RecommendationLog.objects.create(
            user=self.user,
            task=self.task2,
            recommended_at=timezone.now(),
            status=RecommendationLog.Status.RECOMMENDED,
            source_mode=RecommendationLog.SourceMode.TRAINING,
            rank_position=2,
        )
        stale_task = Task.objects.create(
            type=self.task1.type,
            title="StaleTask",
            subject=self.subject,
            exam_version=self.exam_version,
        )
        solved_task = Task.objects.create(
            type=self.task1.type,
            title="SolvedTask",
            subject=self.subject,
            exam_version=self.exam_version,
        )
        fresh_task = Task.objects.create(
            type=self.task1.type,
            title="FreshTask",
            subject=self.subject,
            exam_version=self.exam_version,
        )

        RecommendationLog.objects.create(
            user=self.user,
            task=stale_task,
            recommended_at=timezone.now(),
            status=RecommendationLog.Status.RECOMMENDED,
            source_mode=RecommendationLog.SourceMode.TRAINING,
            rank_position=1,
        )
        Attempt.objects.create(
            user=self.user,
            task=solved_task,
            is_correct=True,
            is_valid_attempt=True,
            checked_at=timezone.now(),
            mode=Attempt.Mode.TRAINING,
            attempt_number=1,
            score=1,
            max_score=1,
        )

        tasks = recommend_tasks(
            self.user,
            limit=1,
            log=True,
            source_mode=RecommendationLog.SourceMode.TRAINING,
        )

        self.assertEqual([task.title for task in tasks], ["FreshTask"])
        log = RecommendationLog.objects.filter(user=self.user, task=fresh_task).latest("id")
        self.assertEqual(log.status, RecommendationLog.Status.RECOMMENDED)
        self.assertEqual(log.source_mode, RecommendationLog.SourceMode.TRAINING)
        self.assertEqual(log.rank_position, 1)
        self.assertIsNotNone(log.recommended_at)
        self.assertEqual(log.score_snapshot["mode"], "legacy")
        self.assertEqual(log.reason_snapshot["mode"], "legacy")

    def test_mark_recommendation_opened_updates_status(self):
        task = Task.objects.create(
            type=self.task1.type,
            title="OpenTask",
            subject=self.subject,
            exam_version=self.exam_version,
        )
        recommendation = RecommendationLog.objects.create(
            user=self.user,
            task=task,
            recommended_at=timezone.now(),
            status=RecommendationLog.Status.RECOMMENDED,
            source_mode=RecommendationLog.SourceMode.TRAINING,
            rank_position=1,
        )
        recommendation = mark_recommendation_opened(recommendation)
        self.assertIsNotNone(recommendation)
        self.assertEqual(recommendation.status, RecommendationLog.Status.OPENED)

    def test_attempt_attaches_to_latest_recommendation_and_completes(self):
        task = Task.objects.create(
            type=self.task1.type,
            title="TrackedTask",
            subject=self.subject,
            exam_version=self.exam_version,
        )
        recommendation = RecommendationLog.objects.create(
            user=self.user,
            task=task,
            recommended_at=timezone.now(),
            status=RecommendationLog.Status.OPENED,
            source_mode=RecommendationLog.SourceMode.TRAINING,
            rank_position=1,
        )

        attempt = Attempt.objects.create(
            user=self.user,
            task=task,
            is_correct=True,
            is_valid_attempt=True,
            checked_at=timezone.now(),
            mode=Attempt.Mode.TRAINING,
            attempt_number=1,
            score=1,
            max_score=1,
        )

        attempt.refresh_from_db()
        recommendation.refresh_from_db()
        self.assertEqual(attempt.source_recommendation_id, recommendation.id)
        self.assertEqual(recommendation.attempt_id, attempt.id)
        self.assertEqual(recommendation.status, RecommendationLog.Status.COMPLETED)
        self.assertTrue(recommendation.completed)

    def test_recommend_task_candidates_include_breakdown_and_snapshots(self):
        weak_tag = TaskTag.objects.create(subject=self.subject, name="Explain tag")
        task = Task.objects.create(
            type=self.task1.type,
            title="ExplainedTask",
            subject=self.subject,
            exam_version=self.exam_version,
            difficulty_level=30,
            priority_manual=1.2,
        )
        task.tags.add(weak_tag)
        TagMastery.objects.create(
            user=self.user,
            task_tag=weak_tag,
            mastery=0.25,
            coverage=0.4,
            progress=0.4,
            confidence=0.7,
            stability=0.3,
            last_seen_at=timezone.now() - timedelta(days=4),
            last_success_at=timezone.now() - timedelta(days=4),
            attempts_total=2,
            successes_total=1,
        )

        candidates = recommend_task_candidates(
            self.user,
            log=True,
            source_mode=RecommendationLog.SourceMode.TRAINING,
            exclude_recent=False,
            exclude_solved=False,
        )

        candidate = next(item for item in candidates if item.task.id == task.id)
        self.assertEqual(candidate.task.title, "ExplainedTask")
        self.assertEqual(candidate.score_snapshot["mode"], "mvp")
        self.assertIn("weak_gain", candidate.score_snapshot)
        self.assertEqual(candidate.reason_snapshot["mode"], "mvp")
        self.assertEqual(candidate.weak_tags_snapshot[0]["tag_name"], weak_tag.name)
        self.assertGreater(candidate.coverage_gain_snapshot, 0.0)
        self.assertGreaterEqual(candidate.spacing_gain_snapshot, 0.0)

        log = RecommendationLog.objects.filter(user=self.user, task=task).latest("id")
        self.assertEqual(log.score_snapshot["mode"], "mvp")
        self.assertEqual(log.weak_tags_snapshot[0]["tag_name"], weak_tag.name)
