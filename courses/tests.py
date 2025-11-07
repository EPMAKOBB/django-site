from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.recsys.models import (
    Attempt,
    Skill,
    SkillMastery,
    Task,
    TaskPreGeneratedDataset,
    TaskSkill,
    TaskType,
)
from courses.models import (
    Course,
    CourseEnrollment,
    CourseModule,
    CourseModuleItem,
)
from subjects.models import Subject


class ModuleDetailTaskAnswerTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="student", password="secret"
        )
        self.client.force_login(self.user)

        self.subject = Subject.objects.create(name="Математика")
        self.skill = Skill.objects.create(subject=self.subject, name="Алгебра")
        self.task_type = TaskType.objects.create(subject=self.subject, name="База")
        self.task = Task.objects.create(
            subject=self.subject,
            type=self.task_type,
            title="Сложение",
            description="Найдите значение 2 + 2",
            correct_answer={"value": 4},
        )
        TaskSkill.objects.create(task=self.task, skill=self.skill)

        self.course = Course.objects.create(
            slug="math-course",
            title="Математический курс",
            subtitle="",
        )
        self.module = CourseModule.objects.create(
            course=self.course,
            slug="algebra-module",
            title="Алгебра",
            kind=CourseModule.Kind.SKILL,
            skill=self.skill,
        )
        self.item = CourseModuleItem.objects.create(
            module=self.module,
            kind=CourseModuleItem.ItemKind.TASK,
            task=self.task,
            position=1,
        )
        CourseEnrollment.objects.create(
            course=self.course,
            student=self.user,
            status=CourseEnrollment.Status.ENROLLED,
        )

        self.url = self.module.get_absolute_url()

    def test_task_form_renders_answer_fields(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "module-detail__task-form")
        self.assertContains(response, 'name="action" value="submit-answer"', html=False)
        self.assertContains(response, 'name="answer__value"', html=False)

    def test_submit_correct_answer_creates_attempt_and_updates_mastery(self):
        payload = {
            "item_id": str(self.item.id),
            "action": "submit-answer",
            "answer__value": "4",
        }
        response = self.client.post(self.url, data=payload)
        self.assertEqual(response.status_code, 302)

        attempt = Attempt.objects.get()
        self.assertTrue(attempt.is_correct)
        mastery = SkillMastery.objects.get(user=self.user, skill=self.skill)
        self.assertEqual(mastery.mastery, 0.2)

    def test_submit_invalid_answer_shows_errors(self):
        payload = {
            "item_id": str(self.item.id),
            "action": "submit-answer",
            "answer__value": "",
        }
        response = self.client.post(self.url, data=payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Заполните поле «Ответ».")
        self.assertEqual(Attempt.objects.count(), 0)


class ModuleDetailPreGeneratedTaskTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="dynamic-student", password="secret"
        )
        self.client.force_login(self.user)

        self.subject = Subject.objects.create(name="Dynamic subject")
        self.skill = Skill.objects.create(subject=self.subject, name="Dynamic skill")
        self.task_type = TaskType.objects.create(subject=self.subject, name="Dynamic type")
        self.task = Task.objects.create(
            subject=self.subject,
            type=self.task_type,
            title="Dynamic task",
            description="a = {value}",
            correct_answer={"value": 0},
            is_dynamic=True,
            dynamic_mode=Task.DynamicMode.PRE_GENERATED,
            rendering_strategy=Task.RenderingStrategy.MARKDOWN,
        )
        TaskSkill.objects.create(task=self.task, skill=self.skill)
        TaskPreGeneratedDataset.objects.create(
            task=self.task,
            parameter_values={"value": 7},
            correct_answer={"value": 7},
        )

        self.course = Course.objects.create(
            slug="dynamic-course",
            title="Dynamic course",
            subtitle="",
        )
        self.module = CourseModule.objects.create(
            course=self.course,
            slug="dynamic-module",
            title="Dynamic module",
            kind=CourseModule.Kind.SKILL,
            skill=self.skill,
        )
        self.item = CourseModuleItem.objects.create(
            module=self.module,
            kind=CourseModuleItem.ItemKind.TASK,
            task=self.task,
            position=1,
        )
        CourseEnrollment.objects.create(
            course=self.course,
            student=self.user,
            status=CourseEnrollment.Status.ENROLLED,
        )

        self.url = self.module.get_absolute_url()

    def test_pre_generated_task_renders_dataset_payload(self):
        response = self.client.get(self.url)
        self.assertContains(response, "a = 7")
        self.assertNotContains(response, "{value}")

    def test_pre_generated_task_uses_dataset_answer(self):
        payload = {
            "item_id": str(self.item.id),
            "action": "submit-answer",
            "answer__value": "7",
        }
        response = self.client.post(self.url, data=payload)
        self.assertEqual(response.status_code, 302)
        attempt = Attempt.objects.get()
        self.assertTrue(attempt.is_correct)
