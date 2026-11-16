import io
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.recsys.models import AnswerSchema, ExamVersion, Source, SourceVariant, Subject, Task, TaskType


class FreeResponseImportTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name='Math')
        self.exam = ExamVersion.objects.create(subject=self.subject, name='Draft exam')
        schema = AnswerSchema.objects.create(name='free_response', config={
            'rows': 1, 'cols': 1, 'input_type': 'text', 'ui_hint': 'textarea', 'manual_check': True})
        self.task_type = TaskType.objects.create(subject=self.subject, exam_version=self.exam,
            name='13', display_order=13, answer_schema=schema, max_score=2)
        source = Source.objects.create(name='Demo', exam_version=self.exam)
        self.variant = SourceVariant.objects.create(source=source, label='Demo')
        self.entry = {'type_number': 13, 'slug': '13-01-demo', 'title': 'Example 1',
                      'description': 'a) Solve.\nb) Select roots.',
                      'correct_answer': 'a) All roots.\nb) Roots in the interval.\nCriteria: 0, 1, 2 points.'}

    def run_import(self, entries, apply=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tasks.json'
            path.write_text(json.dumps(entries), encoding='utf-8')
            call_command('import_free_response_tasks', path=str(path), exam_version_id=self.exam.pk,
                         source_variant_id=self.variant.pk, apply=apply, stdout=io.StringIO())

    def test_preview_does_not_write(self):
        self.run_import([self.entry])
        self.assertFalse(Task.objects.exists())

    def test_import_sets_manual_scoring_even_for_binary_type(self):
        self.run_import([self.entry], apply=True)
        task = Task.objects.get()
        self.assertEqual(task.correct_answer, self.entry['correct_answer'])
        self.assertEqual(task.status, 'draft')
        self.assertEqual(task.get_scoring_scheme(), 'manual_scaled')
        self.assertEqual(task.max_score, 2)
        placement = task.placements.get()
        self.assertEqual(placement.scoring_scheme, 'manual_scaled')
        self.assertEqual(placement.answer_schema_id, self.task_type.answer_schema_id)

    def test_rejects_grid_and_duplicate_input_without_partial_writes(self):
        for entry in (dict(self.entry, correct_answer=['answer'] + [''] * 16), self.entry):
            with self.subTest(entry=entry):
                with self.assertRaises(CommandError):
                    self.run_import([self.entry, entry], apply=True)
                self.assertFalse(Task.objects.exists())

    def test_fixes_only_unpublished_draft(self):
        call_command('fix_free_response_scoring', exam_version_id=self.exam.pk, apply=True, stdout=io.StringIO())
        self.task_type.refresh_from_db()
        self.assertEqual(self.task_type.scoring_scheme, 'manual_scaled')
        self.exam.status = ExamVersion.Status.ACTIVE
        self.exam.save()
        with self.assertRaises(CommandError):
            call_command('fix_free_response_scoring', exam_version_id=self.exam.pk, apply=True)
