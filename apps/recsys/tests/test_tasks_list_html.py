from django.test import TestCase
from django.urls import reverse

from apps.recsys.models import Task
from apps.recsys.tests.factories import create_task


class TasksListHTMLRenderingTests(TestCase):
    def test_tasks_list_renders_html_description(self):
        task = create_task()
        svg_html = (
            '<div class="diagram">'
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50">'
            '<rect width="100" height="50" fill="red" />'
            "</svg>"
            "</div>"
        )
        task.description = svg_html
        task.rendering_strategy = Task.RenderingStrategy.HTML
        task.save(update_fields=["description", "rendering_strategy"])

        response = self.client.get(reverse("tasks_list"))

        content = response.content.decode("utf-8")
        self.assertIn(svg_html, content)
        self.assertIn('data-format="html"', content)
        self.assertNotIn("&lt;svg", content)
