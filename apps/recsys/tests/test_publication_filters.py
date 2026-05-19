from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.recsys.models import (
    ExamBlueprint,
    ExamBlueprintItem,
    ExamVersion,
    Task,
    TaskType,
    VariantAssignment,
    VariantAttempt,
    VariantTemplate,
)
from apps.recsys.recommendation import recommend_tasks
from apps.recsys.service_utils import variants as variant_service
from subjects.models import Subject


class PublicationFiltersTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="student")
        self.subject = Subject.objects.create(name="Subject")
        self.exam = ExamVersion.objects.create(
            name="Exam",
            slug="exam",
            subject=self.subject,
        )
        self.task_type = TaskType.objects.create(
            name="Type",
            slug="type",
            subject=self.subject,
            exam_version=self.exam,
        )

    def _task(self, title: str, status: str):
        return Task.objects.create(
            type=self.task_type,
            title=title,
            subject=self.subject,
            exam_version=self.exam,
            status=status,
        )

    def test_public_task_list_hides_drafts(self):
        published = self._task("Published task", Task.Status.PUBLISHED)
        self._task("Draft task", Task.Status.DRAFT)

        response = self.client.get(reverse("tasks_list"))

        task_ids = [row["task"].id for row in response.context["task_rows"]]
        self.assertEqual(task_ids, [published.id])

    def test_recommendations_only_use_published_tasks(self):
        published = self._task("Published task", Task.Status.PUBLISHED)
        self._task("Draft task", Task.Status.DRAFT)

        tasks = recommend_tasks(self.user, exclude_recent=False, exclude_solved=False)

        self.assertEqual([task.id for task in tasks], [published.id])

    def test_public_static_variant_hidden_until_all_tasks_are_published(self):
        published = self._task("Published task", Task.Status.PUBLISHED)
        draft = self._task("Draft task", Task.Status.DRAFT)
        template = VariantTemplate.objects.create(
            name="Public variant",
            exam_version=self.exam,
            is_public=True,
        )
        variant_service.ensure_variant_page(template, is_public=True)
        template.template_tasks.create(task=published, order=1)
        template.template_tasks.create(task=draft, order=2)

        response = self.client.get(reverse("exam-public-blocks", kwargs={"exam_slug": self.exam.slug}))
        self.assertNotContains(response, "Public variant")

        draft.status = Task.Status.PUBLISHED
        draft.save(update_fields=["status"])
        response = self.client.get(reverse("exam-public-blocks", kwargs={"exam_slug": self.exam.slug}))
        self.assertContains(response, "Public variant")

    def test_public_variant_direct_url_404_when_contains_draft_task(self):
        draft = self._task("Draft task", Task.Status.DRAFT)
        template = VariantTemplate.objects.create(
            name="Blocked variant",
            exam_version=self.exam,
            is_public=True,
        )
        page = variant_service.ensure_variant_page(template, is_public=True)
        template.template_tasks.create(task=draft, order=1)

        response = self.client.get(reverse("variant-page", kwargs={"slug": page.slug}))

        self.assertEqual(response.status_code, 404)

    def test_private_assigned_variant_with_draft_task_start_does_not_500(self):
        draft = self._task("Draft task", Task.Status.DRAFT)
        self._task("Replacement task", Task.Status.PUBLISHED)
        blueprint = ExamBlueprint.objects.create(
            subject=self.subject,
            exam_version=self.exam,
            title="Blueprint",
            is_active=True,
        )
        ExamBlueprintItem.objects.create(
            blueprint=blueprint,
            task_type=self.task_type,
            count=1,
            order=1,
        )
        template = VariantTemplate.objects.create(
            name="Assigned blocked variant",
            exam_version=self.exam,
            kind=VariantTemplate.Kind.PERSONAL,
            is_public=False,
        )
        page = variant_service.ensure_variant_page(template, is_public=False)
        template.template_tasks.create(task=draft, order=1)
        assignment = VariantAssignment.objects.create(template=template, user=self.user)
        self.client.force_login(self.user)

        response = self.client.get(reverse("variant-page", kwargs={"slug": page.slug}))

        self.assertContains(response, "Вариант временно недоступен")
        self.assertContains(response, "Собрать новый")
        self.assertContains(response, "disabled")
        self.assertNotContains(response, 'id="variant-start-form"')

        response = self.client.post(
            reverse("variant-page", kwargs={"slug": page.slug}),
            {"action": "start"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Вариант временно недоступен")
        self.assertFalse(VariantAttempt.objects.exists())

        response = self.client.post(
            reverse("variant-page", kwargs={"slug": page.slug}),
            {"action": "rebuild_personal"},
        )

        self.assertEqual(response.status_code, 302)
        assignment.refresh_from_db()
        self.assertIsNotNone(assignment.deadline)
        self.assertEqual(VariantAssignment.objects.filter(user=self.user).count(), 2)

    def test_started_personal_variant_can_be_abandoned_and_rebuilt(self):
        task = self._task("Started task", Task.Status.PUBLISHED)
        self._task("Replacement task", Task.Status.PUBLISHED)
        blueprint = ExamBlueprint.objects.create(
            subject=self.subject,
            exam_version=self.exam,
            title="Blueprint",
            is_active=True,
        )
        ExamBlueprintItem.objects.create(
            blueprint=blueprint,
            task_type=self.task_type,
            count=1,
            order=1,
        )
        template = VariantTemplate.objects.create(
            name="Started personal variant",
            exam_version=self.exam,
            kind=VariantTemplate.Kind.PERSONAL,
            is_public=False,
        )
        page = variant_service.ensure_variant_page(template, is_public=False)
        template.template_tasks.create(task=task, order=1)
        assignment = VariantAssignment.objects.create(template=template, user=self.user)
        attempt = VariantAttempt.objects.create(assignment=assignment, attempt_number=1)
        self.client.force_login(self.user)

        response = self.client.get(reverse("variant-page", kwargs={"slug": page.slug}))

        self.assertContains(response, "Продолжить решение варианта")
        self.assertContains(response, "Отказаться от решения и собрать новый")

        response = self.client.post(
            reverse("variant-page", kwargs={"slug": page.slug}),
            {"action": "rebuild_personal"},
        )

        self.assertEqual(response.status_code, 302)
        attempt.refresh_from_db()
        assignment.refresh_from_db()
        self.assertIsNotNone(attempt.completed_at)
        self.assertIsNotNone(assignment.deadline)
        self.assertEqual(VariantAssignment.objects.filter(user=self.user).count(), 2)

    def test_completed_personal_variant_is_not_reused_for_new_personal_build(self):
        task = self._task("Completed personal task", Task.Status.PUBLISHED)
        blueprint = ExamBlueprint.objects.create(
            subject=self.subject,
            exam_version=self.exam,
            title="Blueprint",
            is_active=True,
        )
        ExamBlueprintItem.objects.create(
            blueprint=blueprint,
            task_type=self.task_type,
            count=1,
            order=1,
        )
        template = VariantTemplate.objects.create(
            name="Completed personal variant",
            exam_version=self.exam,
            kind=VariantTemplate.Kind.PERSONAL,
            is_public=False,
        )
        template.template_tasks.create(task=task, order=1)
        assignment = VariantAssignment.objects.create(template=template, user=self.user)
        VariantAttempt.objects.create(
            assignment=assignment,
            attempt_number=1,
            completed_at=task.created_at,
        )

        new_assignment = variant_service.build_personal_assignment_from_blueprint(
            user=self.user,
            exam_version=self.exam,
        )

        self.assertNotEqual(new_assignment.pk, assignment.pk)
        self.assertEqual(VariantAssignment.objects.filter(user=self.user).count(), 2)
