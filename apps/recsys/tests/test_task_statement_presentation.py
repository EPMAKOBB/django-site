from django.test import TestCase

from apps.recsys.models import ExamVersion, Subject, Task, TaskAttachment, TaskType
from apps.recsys.presentation.tasks import build_task_statement_payload


class TaskStatementPresentationTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="Subject")
        self.exam_version = ExamVersion.objects.create(name="Exam", subject=self.subject)
        self.task_type = TaskType.objects.create(
            name="Type",
            subject=self.subject,
            exam_version=self.exam_version,
        )

    def test_statement_payload_normalizes_html_once_for_all_surfaces(self):
        task = Task.objects.create(
            subject=self.subject,
            exam_version=self.exam_version,
            type=self.task_type,
            title="Task",
            rendering_strategy=Task.RenderingStrategy.HTML,
            description=(
                "<p>Before</p>"
                '<div class="answer-shell"><input value=""></div>'
                "<table><tr><td></td><td>*</td></tr></table>"
                "<p>After</p>"
            ),
            image="tasks/exam/images/task.svg",
            status=Task.Status.PUBLISHED,
        )
        TaskAttachment.objects.create(
            task=task,
            kind=TaskAttachment.Kind.FILE,
            file="tasks/exam/files/data.txt",
            label="A",
            download_name_override="data.txt",
        )
        TaskAttachment.objects.create(
            task=task,
            kind=TaskAttachment.Kind.IMAGE,
            file="tasks/exam/images/extra.svg",
            label="img",
        )

        payload = build_task_statement_payload(task=task)

        self.assertIn("<p>Before</p>", payload["task_body_html"])
        self.assertIn("<p>After</p>", payload["task_body_html"])
        self.assertNotIn("answer-shell", payload["task_body_html"])
        self.assertNotIn("<input", payload["task_body_html"])
        self.assertIn("<td></td>", payload["task_body_html"])
        self.assertTrue(payload["image"].endswith("/tasks/exam/images/task.svg"))
        self.assertEqual(
            payload["attachments"],
            [
                {
                    "id": task.attachments.get(kind=TaskAttachment.Kind.FILE).id,
                    "name": "data.txt",
                    "label": "A",
                    "url": "/media/tasks/exam/files/data.txt",
                }
            ],
        )

    def test_statement_payload_uses_image_attachment_for_inline_data_image(self):
        task = Task.objects.create(
            subject=self.subject,
            exam_version=self.exam_version,
            type=self.task_type,
            title="Task with inline image",
            rendering_strategy=Task.RenderingStrategy.HTML,
            description=(
                "<p>Before</p>"
                '<p><img src="data:image/png;base64,abc" alt="schema"></p>'
                "<p>After</p>"
            ),
            status=Task.Status.PUBLISHED,
        )
        TaskAttachment.objects.create(
            task=task,
            kind=TaskAttachment.Kind.IMAGE,
            file="tasks/exam/images/schema.png",
            label="img",
        )

        payload = build_task_statement_payload(task=task)

        self.assertIn('<img alt="schema" src="/media/tasks/exam/images/schema.png"/>', payload["task_body_html"])
        self.assertNotIn("data:image", payload["task_body_html"])
        self.assertEqual(payload["image"], "")
        self.assertEqual(payload["attachments"], [])

    def test_statement_payload_falls_back_to_image_attachment_when_body_has_no_image(self):
        task = Task.objects.create(
            subject=self.subject,
            exam_version=self.exam_version,
            type=self.task_type,
            title="Task with image attachment",
            rendering_strategy=Task.RenderingStrategy.HTML,
            description="<p>Statement</p>",
            status=Task.Status.PUBLISHED,
        )
        TaskAttachment.objects.create(
            task=task,
            kind=TaskAttachment.Kind.IMAGE,
            file="tasks/exam/images/schema.png",
            label="img",
        )

        payload = build_task_statement_payload(task=task)

        self.assertEqual(payload["image"], "/media/tasks/exam/images/schema.png")
        self.assertEqual(payload["attachments"], [])

    def test_statement_payload_decodes_escaped_html_descriptions(self):
        task = Task.objects.create(
            subject=self.subject,
            exam_version=self.exam_version,
            type=self.task_type,
            title="Escaped HTML task",
            rendering_strategy=Task.RenderingStrategy.HTML,
            description=(
                "&lt;p&gt;Before&lt;/p&gt;"
                "&lt;p&gt;&lt;img src=&quot;/media/tasks/exam/images/schema.png&quot;&gt;&lt;/p&gt;"
                "&lt;p&gt;After&lt;/p&gt;"
            ),
            status=Task.Status.PUBLISHED,
        )

        payload = build_task_statement_payload(task=task)

        self.assertIn("<p>Before</p>", payload["task_body_html"])
        self.assertIn('<img src="/media/tasks/exam/images/schema.png"/>', payload["task_body_html"])
        self.assertIn("<p>After</p>", payload["task_body_html"])
        self.assertNotIn("&lt;p&gt;", payload["task_body_html"])

    def test_statement_payload_detects_html_when_strategy_is_missing(self):
        task = Task.objects.create(
            subject=self.subject,
            exam_version=self.exam_version,
            type=self.task_type,
            title="Implicit HTML task",
            rendering_strategy=Task.RenderingStrategy.PLAIN,
            description=(
                "<p>Before</p>"
                '<p><img src="/media/tasks/exam/images/schema.png"></p>'
                "<p>After</p>"
            ),
            status=Task.Status.PUBLISHED,
        )

        payload = build_task_statement_payload(task=task)

        self.assertIn("<p>Before</p>", payload["task_body_html"])
        self.assertIn('<img src="/media/tasks/exam/images/schema.png"/>', payload["task_body_html"])
        self.assertNotIn("&lt;p&gt;", payload["task_body_html"])
