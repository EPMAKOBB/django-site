from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.recsys.models import ExamVersion, Source, SourceVariant, Task, TaskType
from subjects.models import Subject


class VariantBuilderViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(
            username="staff_builder",
            password="test-pass-123",
            is_staff=True,
        )
        self.client.force_login(self.staff)
        self.url = reverse("tasks_variant_builder")

        self.subject = Subject.objects.create(name="Математика")
        self.other_subject = Subject.objects.create(name="Информатика")

        self.exam = ExamVersion.objects.create(subject=self.subject, name="ЕГЭ-2026")
        self.other_exam = ExamVersion.objects.create(subject=self.subject, name="ЕГЭ-2025")
        self.foreign_exam = ExamVersion.objects.create(
            subject=self.other_subject,
            name="ЕГЭ-2026",
        )

        self.source = Source.objects.create(name="Статград", slug="statgrad")
        self.other_source = Source.objects.create(name="ФИПИ", slug="fipi")

        self.source_variant = SourceVariant.objects.create(
            source=self.source,
            label="Вариант 1",
            slug="var-1",
        )
        self.other_source_variant = SourceVariant.objects.create(
            source=self.source,
            label="Вариант 2",
            slug="var-2",
        )

    def _make_task(self, *, title: str, task_type: TaskType, exam: ExamVersion, source_variant=None):
        return Task.objects.create(
            subject=exam.subject,
            exam_version=exam,
            type=task_type,
            title=title,
            source=source_variant.source if source_variant else self.source,
            source_variant=source_variant,
        )

    def test_tasks_sorted_by_type_display_order(self):
        type_late = TaskType.objects.create(
            subject=self.subject,
            exam_version=self.exam,
            name="Тип 3",
            slug="type-3",
            display_order=30,
        )
        type_early = TaskType.objects.create(
            subject=self.subject,
            exam_version=self.exam,
            name="Тип 1",
            slug="type-1",
            display_order=10,
        )
        type_mid = TaskType.objects.create(
            subject=self.subject,
            exam_version=self.exam,
            name="Тип 2",
            slug="type-2",
            display_order=20,
        )

        late_task = self._make_task(title="Задача поздняя", task_type=type_late, exam=self.exam)
        early_task = self._make_task(title="Задача ранняя", task_type=type_early, exam=self.exam)
        mid_task = self._make_task(title="Задача средняя", task_type=type_mid, exam=self.exam)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        ordered_ids = list(response.context["tasks"].values_list("id", flat=True))
        self.assertEqual(ordered_ids[:3], [early_task.id, mid_task.id, late_task.id])

    def test_filters_by_subject_exam_source_and_variant(self):
        type_main = TaskType.objects.create(
            subject=self.subject,
            exam_version=self.exam,
            name="Основной тип",
            slug="main-type",
            display_order=1,
        )
        type_other_exam = TaskType.objects.create(
            subject=self.subject,
            exam_version=self.other_exam,
            name="Другой экзамен",
            slug="other-exam-type",
            display_order=1,
        )
        type_foreign = TaskType.objects.create(
            subject=self.other_subject,
            exam_version=self.foreign_exam,
            name="Чужой предмет",
            slug="foreign-type",
            display_order=1,
        )

        target = self._make_task(
            title="Нужная задача",
            task_type=type_main,
            exam=self.exam,
            source_variant=self.source_variant,
        )
        self._make_task(
            title="Другой вариант источника",
            task_type=type_main,
            exam=self.exam,
            source_variant=self.other_source_variant,
        )
        self._make_task(
            title="Другой экзамен",
            task_type=type_other_exam,
            exam=self.other_exam,
            source_variant=self.source_variant,
        )
        Task.objects.create(
            subject=self.other_subject,
            exam_version=self.foreign_exam,
            type=type_foreign,
            title="Другой предмет",
            source=self.other_source,
        )

        response = self.client.get(
            self.url,
            {
                "subject": self.subject.id,
                "exam_version": self.exam.id,
                "source": self.source.id,
                "source_variant": self.source_variant.id,
            },
        )
        self.assertEqual(response.status_code, 200)

        filtered_ids = list(response.context["tasks"].values_list("id", flat=True))
        self.assertEqual(filtered_ids, [target.id])

