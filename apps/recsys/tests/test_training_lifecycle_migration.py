from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class TrainingLifecycleMigrationTests(TransactionTestCase):
    def test_existing_work_normalization_preserves_checks_and_exam_results(self):
        before = [("recsys", "0053_exam_catalog_revision")]
        after = [("recsys", "0054_training_lifecycle")]
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        old = executor.loader.project_state(before).apps
        try:
            User = old.get_model(settings.AUTH_USER_MODEL)
            Subject = old.get_model("subjects", "Subject")
            Exam = old.get_model("recsys", "ExamVersion")
            Template = old.get_model("recsys", "VariantTemplate")
            Assignment = old.get_model("recsys", "VariantAssignment")
            Work = old.get_model("recsys", "VariantAttempt")
            Task = old.get_model("recsys", "Task")
            Type = old.get_model("recsys", "TaskType")
            Row = old.get_model("recsys", "VariantTask")
            Check = old.get_model("recsys", "VariantTaskAttempt")
            user = User.objects.create(username="migration-training-user")
            subject = Subject.objects.create(name="Migration subject")
            exam = Exam.objects.create(name="Migration exam", subject=subject)
            task_type = Type.objects.create(name="Type", subject=subject, exam_version=exam)
            task = Task.objects.create(title="Frozen question", description="Statement", type=task_type, subject=subject)
            template = Template.objects.create(name="Migration template", exam_version=exam)
            assignment = Assignment.objects.create(user=user, template=template)
            row = Row.objects.create(template=template, task=task, order=1)
            now = timezone.now()
            first = Work.objects.create(assignment=assignment, attempt_number=1, mode="training",
                                        active_variant_task=row, active_started_at=now-timedelta(hours=4), last_seen_at=now-timedelta(hours=3))
            latest = Work.objects.create(assignment=assignment, attempt_number=2, mode="training")
            completed = Work.objects.create(assignment=assignment, attempt_number=3, mode="training", completed_at=now)
            probe = Work.objects.create(assignment=assignment, attempt_number=4, mode="exam", completed_at=now)
            snapshot = {"task":{"description":"Original statement"}, "response":{"value":"42"}}
            check = Check.objects.create(variant_attempt=first, variant_task=row, task=task, attempt_number=1,
                                         is_correct=True, task_snapshot=snapshot)
            Work.objects.filter(pk=first.pk).update(started_at=now-timedelta(minutes=10))
            Work.objects.filter(pk=latest.pk).update(started_at=now-timedelta(minutes=1))
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            new = executor.loader.project_state(after).apps
            Work = new.get_model("recsys", "VariantAttempt")
            Check = new.get_model("recsys", "VariantTaskAttempt")
            TimeLog = new.get_model("recsys", "VariantTaskTimeLog")
            self.assertIsNotNone(Work.objects.get(pk=first.pk).archived_at)
            self.assertIsNone(Work.objects.get(pk=latest.pk).archived_at)
            legacy = Work.objects.get(pk=completed.pk)
            self.assertEqual(legacy.legacy_completed_at, now)
            self.assertEqual(legacy.archived_at, now)
            self.assertIsNone(legacy.completed_at)
            self.assertEqual(Work.objects.get(pk=probe.pk).completed_at, now)
            self.assertIsNone(Work.objects.get(pk=probe.pk).archived_at)
            self.assertEqual(Check.objects.get(pk=check.pk).task_snapshot, snapshot)
            self.assertTrue(Check.objects.get(pk=check.pk).is_correct)
            self.assertEqual(TimeLog.objects.get(variant_attempt_id=first.pk).duration, timedelta(hours=1, seconds=90))
            self.assertIsNone(Work.objects.get(pk=first.pk).active_variant_task_id)
        finally:
            MigrationExecutor(connection).migrate(after)
