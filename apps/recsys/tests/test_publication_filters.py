from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.recsys.models import ExamVersion, Task, TaskType, VariantTemplate
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
