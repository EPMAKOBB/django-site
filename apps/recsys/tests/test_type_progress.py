from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.recsys.models import (
    Attempt,
    ExamBlueprint,
    ExamBlueprintItem,
    ExamScoreScale,
    ExamVersion,
    Subject,
    Task,
    TaskTag,
    TaskType,
    TypeMastery,
)
from apps.recsys.service_utils.type_progress import build_type_progress_map
from courses.models import Course, CourseModule, CourseEnrollment
from courses.services import get_base_module_mastery_percent


FIRST_SUCCESS_TAG_RATIO = (
    0.55 * 0.15
    + 0.20 * 0.10
    + 0.15 * 0.08
    + 0.10 * (1 - 2.718281828459045 ** (-1 / 5))
)


class TypeProgressServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="student")
        self.subject = Subject.objects.create(name="Информатика")
        self.exam_version = ExamVersion.objects.create(name="ЕГЭ-2026", subject=self.subject)
        self.task_type = TaskType.objects.create(name="Задача 25", subject=self.subject, exam_version=self.exam_version)
        self.tag_divisors = TaskTag.objects.create(subject=self.subject, name="делители")
        self.tag_masks = TaskTag.objects.create(subject=self.subject, name="маски числа")
        self.optional_tag = TaskTag.objects.create(subject=self.subject, name="опциональный")
        self.task_type.required_tags.add(self.tag_divisors, self.tag_masks)

        self.task_one = Task.objects.create(
            subject=self.subject,
            exam_version=self.exam_version,
            type=self.task_type,
            title="Task #1",
        )
        self.task_one.tags.add(self.tag_divisors, self.optional_tag)

        self.task_two = Task.objects.create(
            subject=self.subject,
            exam_version=self.exam_version,
            type=self.task_type,
            title="Task #2",
        )
        self.task_two.tags.add(self.tag_masks)
        Task.objects.update(status=Task.Status.PUBLISHED)

    def test_effective_mastery_uses_tag_mastery_and_keeps_bank_coverage(self):
        TypeMastery.objects.create(user=self.user, task_type=self.task_type, mastery=1.0)

        Attempt.objects.create(user=self.user, task=self.task_one, is_correct=True)

        progress_map = build_type_progress_map(user=self.user, task_type_ids=[self.task_type.id])
        info = progress_map[self.task_type.id]

        self.assertAlmostEqual(info.coverage_ratio, 0.5)
        self.assertAlmostEqual(info.effective_mastery, FIRST_SUCCESS_TAG_RATIO / 2)
        self.assertEqual(info.required_count, 2)
        self.assertEqual(info.covered_count, 1)
        self.assertSetEqual(info.covered_tag_ids, {self.tag_divisors.id})
        self.assertEqual(len(info.tag_progress), 2)
        divisors_entry = next(entry for entry in info.tag_progress if entry.tag.id == self.tag_divisors.id)
        masks_entry = next(entry for entry in info.tag_progress if entry.tag.id == self.tag_masks.id)
        self.assertEqual(divisors_entry.total_count, 1)
        self.assertEqual(divisors_entry.solved_count, 1)
        self.assertAlmostEqual(divisors_entry.coverage_ratio, 1.0)
        self.assertAlmostEqual(divisors_entry.ratio, FIRST_SUCCESS_TAG_RATIO)
        self.assertEqual(masks_entry.total_count, 1)
        self.assertEqual(masks_entry.solved_count, 0)
        self.assertAlmostEqual(masks_entry.coverage_ratio, 0.0)
        self.assertAlmostEqual(masks_entry.ratio, 0.0)

        Attempt.objects.create(user=self.user, task=self.task_two, is_correct=True)
        progress_map = build_type_progress_map(user=self.user, task_type_ids=[self.task_type.id])
        info = progress_map[self.task_type.id]

        self.assertAlmostEqual(info.coverage_ratio, 1.0)
        self.assertAlmostEqual(info.effective_mastery, FIRST_SUCCESS_TAG_RATIO)
        self.assertSetEqual(info.covered_tag_ids, {self.tag_divisors.id, self.tag_masks.id})
        for entry in info.tag_progress:
            self.assertAlmostEqual(entry.coverage_ratio, 1.0)
            self.assertAlmostEqual(entry.ratio, FIRST_SUCCESS_TAG_RATIO)
            self.assertEqual(entry.total_count, 1)
            self.assertEqual(entry.solved_count, 1)

    def test_missing_mastery_defaults_to_zero(self):
        progress_map = build_type_progress_map(user=self.user, task_type_ids=[self.task_type.id])
        info = progress_map[self.task_type.id]
        self.assertEqual(info.effective_mastery, 0.0)
        self.assertEqual(info.coverage_ratio, 0.0)
        self.assertEqual(info.required_count, 2)
        self.assertEqual(info.covered_count, 0)
        self.assertEqual(info.covered_tag_ids, frozenset())
        self.assertTrue(all(entry.coverage_ratio == 0.0 for entry in info.tag_progress))
        self.assertTrue(all(entry.ratio == 0.0 for entry in info.tag_progress))

    def test_exam_progress_data_includes_primary_and_secondary_forecast(self):
        self.exam_version.slug = "informatics-2026"
        self.exam_version.save(update_fields=["slug"])
        other_type = TaskType.objects.create(
            name="Task 26",
            subject=self.subject,
            exam_version=self.exam_version,
            max_score=3,
        )
        other_tag = TaskTag.objects.create(subject=self.subject, name="other")
        other_type.required_tags.add(other_tag)
        other_task = Task.objects.create(
            subject=self.subject,
            exam_version=self.exam_version,
            type=other_type,
            title="Task #3",
            status=Task.Status.PUBLISHED,
        )
        other_task.tags.add(other_tag)
        Task.objects.update(status=Task.Status.PUBLISHED)
        blueprint = ExamBlueprint.objects.create(
            subject=self.subject,
            exam_version=self.exam_version,
            is_active=True,
        )
        ExamBlueprintItem.objects.create(
            blueprint=blueprint,
            task_type=self.task_type,
            order=1,
            score_override=2,
        )
        ExamBlueprintItem.objects.create(
            blueprint=blueprint,
            task_type=other_type,
            order=2,
        )
        ExamScoreScale.objects.create(
            exam_version=self.exam_version,
            max_primary=5,
            mapping=[0, 10, 20, 30, 40, 50],
            is_active=True,
        )
        Attempt.objects.create(user=self.user, task=self.task_one, is_correct=True)
        self.client.force_login(self.user)

        response = self.client.get(f"/exams/{self.exam_version.slug}/progress/")

        self.assertEqual(response.status_code, 200)
        forecast = response.json()["score_forecast"]
        self.assertEqual(forecast["primary_score"], 0)
        self.assertEqual(forecast["primary_expected"], 0.1)
        self.assertEqual(forecast["primary_max"], 5)
        self.assertEqual(forecast["secondary_score"], 0)
        self.assertEqual(forecast["secondary_max"], 50)

    def test_course_module_progress_uses_effective_mastery(self):
        course = Course.objects.create(slug="course-1", title="Course")
        module = CourseModule.objects.create(
            course=course,
            slug="module-1",
            title="Module",
            kind=CourseModule.Kind.TASK_TYPE,
            task_type=self.task_type,
        )
        enrollment = CourseEnrollment.objects.create(course=course, student=self.user)

        TypeMastery.objects.create(user=self.user, task_type=self.task_type, mastery=1.0)
        Attempt.objects.create(user=self.user, task=self.task_one, is_correct=True)

        progress_map = build_type_progress_map(user=self.user, task_type_ids=[self.task_type.id])
        percent = get_base_module_mastery_percent(
            self.user,
            module,
            enrollment,
            type_progress_map=progress_map,
        )
        self.assertAlmostEqual(percent, (FIRST_SUCCESS_TAG_RATIO / 2) * 100)

        Attempt.objects.create(user=self.user, task=self.task_two, is_correct=True)
        progress_map = build_type_progress_map(user=self.user, task_type_ids=[self.task_type.id])
        percent = get_base_module_mastery_percent(
            self.user,
            module,
            enrollment,
            type_progress_map=progress_map,
        )
        self.assertAlmostEqual(percent, FIRST_SUCCESS_TAG_RATIO * 100)
