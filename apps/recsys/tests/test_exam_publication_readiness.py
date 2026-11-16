from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from rest_framework.exceptions import ValidationError as ApiValidationError

from apps.recsys.models import (
    Subject, ExamVersion, TaskType, TaskTag, Task, TaskPlacement,
    TaskTypeTransition, ExamBlueprint, ExamBlueprintItem,
)
from apps.recsys.service_utils.exam_rollover import publish_exam, validate_rollover
from apps.recsys.service_utils.variants import build_personal_assignment_from_blueprint


class ExamPublicationReadinessTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="Physics", slug="physics")
        self.exam = ExamVersion.objects.create(
            subject=self.subject, name="OGE 2027", slug="physics-oge-2027",
            year=2027, exam_kind="oge", publication_info={
                "requirements_checked": True, "scale_checked": True,
                "source_document": "Approved specification",
                "document_fingerprint": "preserve-source-evidence",
            },
        )
        self.topic = TaskTag.objects.create(subject=self.subject, name="Mechanics", slug="mechanics")
        self.missing = TaskTag.objects.create(subject=self.subject, name="Electricity", slug="electricity")
        self.blueprint = ExamBlueprint.objects.create(
            exam_version=self.exam, subject=self.subject, time_limit=timedelta(minutes=180),
        )
        self.types, self.tasks = [], []
        for number in (1, 2):
            task_type = TaskType.objects.create(
                subject=self.subject, exam_version=self.exam, name=f"Type {number}", slug=str(number),
            )
            task_type.required_tags.add(self.topic)
            TaskTypeTransition.objects.create(
                target_exam=self.exam, target_type=task_type, relation="added", approved=True,
            )
            task = Task.objects.create(
                subject=self.subject, exam_version=self.exam, type=task_type,
                title=f"Task {number}", slug=f"task-{number}",
                description="Solve this problem", correct_answer={"value": "1"}, status="published",
            )
            task.tags.add(self.topic)
            TaskPlacement.objects.get_or_create(task=task, task_type=task_type)
            ExamBlueprintItem.objects.create(blueprint=self.blueprint, task_type=task_type, order=number, count=1)
            self.types.append(task_type)
            self.tasks.append(task)
        self.types[0].required_tags.add(self.missing)

    def login_admin(self):
        user = get_user_model().objects.create_superuser(username="publication-admin", password="test-password")
        self.client.force_login(user)
        return reverse("admin:recsys_examversion_review_year", args=[self.exam.pk])

    def post_publish(self, url):
        return self.client.post(url, {
            "action": "publish", "source_document": "Approved specification",
            "requirements_checked": "on", "scale_checked": "on",
        })

    def test_incomplete_topic_coverage_is_warning_and_allows_publication(self):
        report = validate_rollover(self.exam)
        self.assertTrue(report["ready"], report["errors"])
        self.assertTrue(report["can_build_variant"])
        self.assertFalse(report["coverage_complete"])
        self.assertEqual(len(report["warnings"]), 1)
        self.assertIn(self.missing.name, report["warnings"][0])
        self.assertEqual(report["type_rows"][0]["count"], 1)
        published = publish_exam(self.exam)
        self.assertEqual(published.status, "active")
        self.assertIsNotNone(published.published_at)

    def test_draft_tasks_do_not_fill_variant_or_published_count(self):
        Task.objects.filter(pk=self.tasks[1].pk).update(status="draft")
        report = validate_rollover(self.exam)
        self.assertFalse(report["ready"])
        self.assertFalse(report["can_build_variant"])
        self.assertEqual(report["type_rows"][1]["count"], 0)
        with self.assertRaises(ValidationError):
            publish_exam(self.exam)

    def test_one_task_cannot_fill_two_positions(self):
        Task.objects.filter(pk=self.tasks[1].pk).update(status="draft")
        TaskPlacement.objects.create(task=self.tasks[0], task_type=self.types[1])
        report = validate_rollover(self.exam)
        self.assertEqual([row["count"] for row in report["type_rows"]], [1, 1])
        self.assertFalse(report["can_build_variant"])
        self.assertFalse(report["ready"])

    def test_review_confirmations_still_block_publication(self):
        for field, value in [("requirements_checked", False), ("scale_checked", False), ("source_document", "")]:
            with self.subTest(field=field):
                original = self.exam.publication_info[field]
                self.exam.publication_info[field] = value
                report = validate_rollover(self.exam)
                self.assertFalse(report["ready"])
                self.assertTrue(report["can_build_variant"])
                self.exam.publication_info[field] = original

    def test_admin_displays_nonblocking_warnings_and_preserves_source_metadata(self):
        url = self.login_admin()
        response = self.client.get(url)
        self.assertContains(response, "Это не мешает публикации экзамена")
        self.assertTrue(response.context["report"]["ready"])
        response = self.post_publish(url)
        self.assertEqual(response.status_code, 302)
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.status, "active")
        self.assertEqual(self.exam.publication_info["document_fingerprint"], "preserve-source-evidence")

    def test_failed_admin_publication_rolls_back_review_confirmations(self):
        self.exam.publication_info["requirements_checked"] = False
        self.exam.save()
        original = dict(self.exam.publication_info)
        Task.objects.filter(pk=self.tasks[1].pk).update(status="draft")
        response = self.post_publish(self.login_admin())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["report"]["ready"])
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.status, "draft")
        self.assertIsNone(self.exam.published_at)
        self.assertEqual(self.exam.publication_info, original)

    def test_runtime_generator_checks_actual_remaining_pool(self):
        exam = publish_exam(self.exam)
        user = get_user_model().objects.create_user(username="student")
        assignment = build_personal_assignment_from_blueprint(user=user, exam_version=exam)
        self.assertEqual(assignment.template.template_tasks.count(), 2)
        with self.assertRaises(ApiValidationError):
            build_personal_assignment_from_blueprint(
                user=user, exam_version=exam, force_new=True, exclude_task_ids=[self.tasks[1].pk],
            )
