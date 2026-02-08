from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.recsys.models import ExamVersion, Source, SourceVariant, Task, TaskType
from subjects.models import Subject


class TaskVariantMapViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(
            username="staff_map",
            password="test-pass-123",
            is_staff=True,
        )
        self.client.force_login(self.staff)

        self.subject = Subject.objects.create(name="Math")
        self.exam = ExamVersion.objects.create(subject=self.subject, name="EGE-2026")
        self.task_type = TaskType.objects.create(
            subject=self.subject,
            exam_version=self.exam,
            name="Type 1",
            slug="type-1",
            display_order=1,
        )
        self.source = Source.objects.create(name="Source A", slug="source-a")
        self.source_variant = SourceVariant.objects.create(
            source=self.source,
            label="Variant 1",
            slug="var-1",
        )
        self.task = Task.objects.create(
            subject=self.subject,
            exam_version=self.exam,
            type=self.task_type,
            source=self.source,
            source_variant=self.source_variant,
            slug="map-task-1",
            title="Task For Map",
            correct_answer={},
        )
        self.url = reverse("tasks_variant_map")

    def test_variant_map_renders_filled_and_empty_cells(self):
        response = self.client.get(
            self.url,
            {"subject": self.subject.id, "exam_version": self.exam.id},
        )
        self.assertEqual(response.status_code, 200)

        self.assertContains(response, f"{reverse('tasks_redact')}?task={self.task.id}")
        self.assertContains(
            response,
            f"{reverse('tasks_upload')}?subject={self.subject.id}&amp;exam_version={self.exam.id}&amp;type={self.task_type.id}",
        )
