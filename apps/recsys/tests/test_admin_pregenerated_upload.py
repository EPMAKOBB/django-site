from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.recsys.models import TaskPreGeneratedDataset
from apps.recsys.tests import factories


class TaskAdminPregeneratedUploadTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="staff",
            email="staff@example.com",
            password="password",
        )
        self.client.force_login(self.user)
        self.task = factories.create_task(title="Test task")
        self.upload_url = reverse("admin:recsys_task_pregenerated_upload")
        self.change_url = reverse("admin:recsys_task_change", args=[self.task.pk])

    def test_get_prefills_task(self):
        response = self.client.get(f"{self.upload_url}?task={self.task.pk}")
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form.initial.get("task"), self.task)

    def test_upload_json_file_imports_datasets(self):
        payload = [
            {
                "parameter_values": {"seed": 1},
                "correct_answer": {"answer": 42},
                "meta": {"difficulty": "easy"},
                "is_active": True,
            },
            {
                "parameter_values": {"seed": 2},
                "correct_answer": {"answer": 24},
                "is_active": False,
            },
        ]
        file_content = json.dumps(payload).encode("utf-8")
        uploaded_file = SimpleUploadedFile(
            "datasets.json",
            file_content,
            content_type="application/json",
        )

        response = self.client.post(
            f"{self.upload_url}?task={self.task.pk}&next={self.change_url}",
            {
                "task": self.task.pk,
                "input_format": "json",
                "file": uploaded_file,
                "next": self.change_url,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.redirect_chain)
        self.assertEqual(response.redirect_chain[-1][0], self.change_url)
        self.assertEqual(response.redirect_chain[-1][1], 302)

        datasets = TaskPreGeneratedDataset.objects.filter(task=self.task).order_by("id")
        self.assertEqual(datasets.count(), 2)
        self.assertTrue(datasets[0].is_active)
        self.assertFalse(datasets[1].is_active)

        messages = list(response.context["messages"])
        self.assertTrue(any("создано 2 вариантов" in str(message) for message in messages))
