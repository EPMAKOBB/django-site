from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.recsys.models import ExamVersion, Skill, Task, TaskAttachment, TaskSkill, TaskType
from subjects.models import Subject


class TaskRedactViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(
            username="staff_redact",
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
        self.skill_old = Skill.objects.create(subject=self.subject, name="Old skill")
        self.skill_new = Skill.objects.create(subject=self.subject, name="New skill")

        self.task = Task.objects.create(
            subject=self.subject,
            exam_version=self.exam,
            type=self.task_type,
            slug="task-redact-1",
            title="Original title",
            description="Original description",
            correct_answer={},
            rendering_strategy=Task.RenderingStrategy.MARKDOWN,
            difficulty_level=10,
            is_dynamic=False,
        )
        TaskSkill.objects.create(task=self.task, skill=self.skill_old, weight=1.0)

        self.url = reverse("tasks_redact")

    def test_get_prefills_selected_task(self):
        response = self.client.get(self.url, {"task": self.task.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_task"].id, self.task.id)
        self.assertContains(response, "task-redact-select")
        self.assertContains(response, self.task.title)

    def test_post_updates_task_and_skill_set(self):
        response = self.client.post(
            self.url,
            data={
                "task_id": str(self.task.id),
                "subject": str(self.subject.id),
                "exam_version": str(self.exam.id),
                "type": str(self.task_type.id),
                "source": "",
                "source_variant": "",
                "slug": "task-redact-1",
                "title": "Updated title",
                "description": "Updated description",
                "answer_inputs": "",
                "correct_answer": "{}",
                "tags": [],
                "rendering_strategy": Task.RenderingStrategy.MARKDOWN,
                "difficulty_level": "33",
                "skills": [str(self.skill_new.id)],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"?task={self.task.id}", response["Location"])

        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "Updated title")
        self.assertEqual(self.task.description, "Updated description")
        self.assertEqual(self.task.difficulty_level, 33)
        self.assertEqual(
            set(TaskSkill.objects.filter(task=self.task).values_list("skill_id", flat=True)),
            {self.skill_new.id},
        )

    def test_post_redirects_to_safe_next(self):
        next_url = f"/tasks/variant-map/?subject={self.subject.id}&exam_version={self.exam.id}"
        response = self.client.post(
            self.url,
            data={
                "task_id": str(self.task.id),
                "next": next_url,
                "subject": str(self.subject.id),
                "exam_version": str(self.exam.id),
                "type": str(self.task_type.id),
                "source": "",
                "source_variant": "",
                "slug": "task-redact-1",
                "title": "Updated title",
                "description": "Updated description",
                "answer_inputs": "",
                "correct_answer": "{}",
                "tags": [],
                "rendering_strategy": Task.RenderingStrategy.MARKDOWN,
                "difficulty_level": "22",
                "skills": [str(self.skill_old.id)],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], next_url)

    def test_post_can_delete_old_and_add_new_attachments(self):
        old_attachment = TaskAttachment.objects.create(
            task=self.task,
            kind=TaskAttachment.Kind.FILE,
            file=SimpleUploadedFile("old.txt", b"old-content", content_type="text/plain"),
            label="old",
            order=1,
        )
        new_file = SimpleUploadedFile("new.txt", b"new-content", content_type="text/plain")

        response = self.client.post(
            self.url,
            data={
                "task_id": str(self.task.id),
                "subject": str(self.subject.id),
                "exam_version": str(self.exam.id),
                "type": str(self.task_type.id),
                "source": "",
                "source_variant": "",
                "slug": "task-redact-1",
                "title": "Updated title with files",
                "description": "Updated description with files",
                "answer_inputs": "",
                "correct_answer": "{}",
                "tags": [],
                "rendering_strategy": Task.RenderingStrategy.MARKDOWN,
                "difficulty_level": "33",
                "skills": [str(self.skill_old.id)],
                "delete_attachment_ids": [str(old_attachment.id)],
                "attachment_names": ["new-name.txt"],
                "attachments": [new_file],
            },
        )
        self.assertEqual(response.status_code, 302)

        attachment_names = list(
            TaskAttachment.objects.filter(task=self.task).values_list("file", flat=True)
        )
        self.assertFalse(
            TaskAttachment.objects.filter(task=self.task, id=old_attachment.id).exists()
        )
        self.assertTrue(any("new-name.txt" in str(name) for name in attachment_names))
