from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.core.management import call_command
from django.test import TestCase

from apps.recsys.models import (
    Subject,
    Task,
    TaskPreGeneratedDataset,
    TaskType,
)


class ImportPreGeneratedPoolCommandTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="Subject")
        self.task_type = TaskType.objects.create(name="Type", subject=self.subject)
        self.task = Task.objects.create(
            title="Task",
            subject=self.subject,
            type=self.task_type,
        )

    def test_import_from_csv(self):
        with NamedTemporaryFile("w", encoding="utf-8", newline="", delete=False) as tmp:
            writer = csv.DictWriter(
                tmp,
                fieldnames=["parameter_values", "correct_answer", "meta", "is_active"],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "parameter_values": json.dumps({"seed": 1}),
                    "correct_answer": json.dumps({"answer": 42}),
                    "meta": json.dumps({"difficulty": "easy"}),
                    "is_active": "true",
                }
            )
            writer.writerow(
                {
                    "parameter_values": json.dumps({"seed": 2}),
                    "correct_answer": json.dumps({"answer": 24}),
                    "meta": "",
                    "is_active": "false",
                }
            )

        path = Path(tmp.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        stdout = io.StringIO()

        call_command(
            "import_pregenerated_pool",
            task_id=self.task.pk,
            format="csv",
            path=str(path),
            stdout=stdout,
        )

        datasets = TaskPreGeneratedDataset.objects.filter(task=self.task).order_by("id")
        self.assertEqual(datasets.count(), 2)
        self.assertEqual(datasets[0].parameter_values, {"seed": 1})
        self.assertEqual(datasets[0].correct_answer, {"answer": 42})
        self.assertEqual(datasets[0].meta, {"difficulty": "easy"})
        self.assertTrue(datasets[0].is_active)
        self.assertFalse(datasets[1].is_active)
        output = stdout.getvalue()
        self.assertIn("Processed 2 row(s); created 2 dataset(s)", output)

    def test_import_from_json_reports_errors(self):
        data = [
            {
                "parameter_values": {"seed": 10},
                "correct_answer": {"answer": 99},
                "meta": {"difficulty": "hard"},
                "is_active": True,
            },
            {
                "parameter_values": "not a dict",
                "correct_answer": {"answer": 1},
            },
        ]

        with NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp:
            json.dump(data, tmp)

        path = Path(tmp.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        stdout = io.StringIO()

        call_command(
            "import_pregenerated_pool",
            task_id=self.task.pk,
            format="json",
            path=str(path),
            stdout=stdout,
        )

        datasets = TaskPreGeneratedDataset.objects.filter(task=self.task)
        self.assertEqual(datasets.count(), 1)
        self.assertEqual(datasets.first().parameter_values, {"seed": 10})
        output = stdout.getvalue()
        self.assertIn("Processed 2 row(s); created 1 dataset(s)", output)
        self.assertIn("Encountered 1 parsing error(s):", output)
        self.assertIn(
            "Строка 2: Поле 'parameter_values' должно быть JSON-объектом",
            output,
        )
