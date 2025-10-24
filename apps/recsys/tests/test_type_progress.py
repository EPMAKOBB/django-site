from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.recsys.models import (
    Attempt,
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

    def test_effective_mastery_limited_by_required_tags(self):
        TypeMastery.objects.create(user=self.user, task_type=self.task_type, mastery=1.0)

        Attempt.objects.create(user=self.user, task=self.task_one, is_correct=True)

        progress_map = build_type_progress_map(user=self.user, task_type_ids=[self.task_type.id])
        info = progress_map[self.task_type.id]

        self.assertAlmostEqual(info.coverage_ratio, 0.5)
        self.assertAlmostEqual(info.effective_mastery, 0.5)
        self.assertEqual(info.required_count, 2)
        self.assertEqual(info.covered_count, 1)
        self.assertSetEqual(info.covered_tag_ids, {self.tag_divisors.id})

        Attempt.objects.create(user=self.user, task=self.task_two, is_correct=True)
        progress_map = build_type_progress_map(user=self.user, task_type_ids=[self.task_type.id])
        info = progress_map[self.task_type.id]

        self.assertAlmostEqual(info.coverage_ratio, 1.0)
        self.assertAlmostEqual(info.effective_mastery, 1.0)
        self.assertSetEqual(info.covered_tag_ids, {self.tag_divisors.id, self.tag_masks.id})

    def test_missing_mastery_defaults_to_zero(self):
        progress_map = build_type_progress_map(user=self.user, task_type_ids=[self.task_type.id])
        info = progress_map[self.task_type.id]
        self.assertEqual(info.effective_mastery, 0.0)
        self.assertEqual(info.coverage_ratio, 0.0)
        self.assertEqual(info.required_count, 2)
        self.assertEqual(info.covered_count, 0)
        self.assertEqual(info.covered_tag_ids, frozenset())

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
        self.assertAlmostEqual(percent, 50.0)

        Attempt.objects.create(user=self.user, task=self.task_two, is_correct=True)
        progress_map = build_type_progress_map(user=self.user, task_type_ids=[self.task_type.id])
        percent = get_base_module_mastery_percent(
            self.user,
            module,
            enrollment,
            type_progress_map=progress_map,
        )
        self.assertAlmostEqual(percent, 100.0)
