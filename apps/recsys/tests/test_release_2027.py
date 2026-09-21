import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.recsys.models import (AnswerSchema, ExamBlueprint, ExamBlueprintItem, ExamVersion,
    Subject, Task, TaskAttachment, TaskPlacement, TaskTag, TaskType)
from apps.recsys.service_utils.release_2027 import prepare_release


class Release2027Tests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.settings_override = override_settings(MEDIA_ROOT=self.root / "media")
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.single = AnswerSchema.objects.create(name="single_uint", config={"rows": 1, "cols": 1, "input_type": "uint"})
        pair = AnswerSchema.objects.create(name="double_uint", config={"rows": 1, "cols": 2, "input_type": "uint"})
        self.subject = Subject.objects.create(name="Информатика", slug="inf")
        self.source = ExamVersion.objects.create(subject=self.subject, name="ЕГЭ 2026", slug="source-2026", year=2026, exam_kind="ege", status="active")
        blueprint = ExamBlueprint.objects.create(subject=self.subject, exam_version=self.source)
        self.old_types = {}
        for number in range(1, 28):
            typ = TaskType.objects.create(subject=self.subject, exam_version=self.source, name=f"тип {number}", slug=str(number), display_order=number,
                answer_schema=pair if number >= 26 else self.single, max_score=2 if number >= 26 else 1)
            tag = TaskTag.objects.create(subject=self.subject, name="Кластеризация" if number == 27 else f"Тема {number}")
            typ.required_tags.add(tag)
            if number == 27:
                anomaly = TaskTag.objects.create(subject=self.subject, name="Аномалии")
                typ.required_tags.add(anomaly)
            task = Task.objects.create(subject=self.subject, exam_version=self.source, type=typ, title=f"Old {number}", slug=f"old-{number}", description="Original", correct_answer=[1, 2] if number >= 26 else 42, status="published")
            task.tags.add(*typ.required_tags.all())
            TaskPlacement.objects.create(task=task, task_type=typ, status="active")
            ExamBlueprintItem.objects.create(blueprint=blueprint, task_type=typ, order=number)
            self.old_types[number] = typ
        items = []
        hashes = {}
        for number, tag in [(13, "Замена цифр"), (16, "Тема 16"), (23, "Кратчайший путь в ориентированном графе"), (24, "Тема 24"), (27, "Кластеризация")]:
            item = dict(number=number, slug=f"release-{number}", title=f"Release {number}", description="Verified", correct_answer=[10, 20] if number == 27 else 42,
                        tags=[tag], source_name="Test demo", source_slug="test-demo", source_description="Test source")
            if number in (23, 24, 27):
                item["file"] = f"demo_{number}.txt"
                content = str(number).encode()
                (self.root / item["file"]).write_bytes(content)
                hashes[item["file"]] = hashlib.sha256(content).hexdigest()
            items.append(item)
        (self.root / "inf_ege_2027_file_hashes.json").write_text(json.dumps(hashes))
        patcher = patch("apps.recsys.service_utils.release_2027.content_spec", return_value=items)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch("apps.recsys.service_utils.release_2027.DATA", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_preview_rolls_back_database_and_never_writes_files(self):
        result = prepare_release(self.source, files_dir=self.root)
        self.assertTrue(result["ready_for_review"], result["errors"])
        self.assertFalse(result["publication_performed"])
        self.assertEqual(ExamVersion.objects.count(), 1)
        self.assertEqual(Task.objects.count(), 27)
        self.assertFalse(TaskAttachment.objects.exists())
        self.assertFalse((self.root / "media").exists())

    def test_apply_repeats_without_duplicates_and_preserves_old_requirements(self):
        result = prepare_release(self.source, files_dir=self.root, apply=True)
        target = ExamVersion.objects.get(pk=result["exam_id"])
        self.assertEqual(target.status, "draft")
        self.assertIsNone(target.published_at)
        self.assertFalse(target.publication_info["requirements_checked"])
        self.assertTrue(self.old_types[27].required_tags.filter(name="Аномалии").exists())
        self.assertFalse(target.task_types.get(slug="27").required_tags.filter(name="Аномалии").exists())
        self.assertEqual(TaskAttachment.objects.count(), 3)
        count = Task.objects.count()
        placement = TaskPlacement.objects.get(task__slug="release-27")
        placement.status = "retired"
        placement.save()
        again = prepare_release(self.source, files_dir=self.root, apply=True)
        self.assertTrue(again["already_prepared"])
        self.assertFalse(again["ready_for_review"])
        placement.refresh_from_db()
        self.assertEqual(placement.status, "retired")
        self.assertEqual(Task.objects.count(), count)
        self.assertEqual(TaskAttachment.objects.count(), 3)

    def test_foreign_target_is_not_overwritten(self):
        ExamVersion.objects.create(subject=self.subject, name="ЕГЭ 2027", year=2027, exam_kind="ege")
        with self.assertRaisesMessage(ValidationError, "перезапись запрещена"):
            prepare_release(self.source, files_dir=self.root, apply=True)
        self.assertEqual(Task.objects.count(), 27)

    def test_changed_file_is_rejected_before_database_writes(self):
        (self.root / "demo_27.txt").write_bytes(b"wrong")
        with self.assertRaisesMessage(ValidationError, "не совпадает"):
            prepare_release(self.source, files_dir=self.root, apply=True)
        self.assertEqual(ExamVersion.objects.count(), 1)

    def test_existing_task_conflict_rolls_back_partial_import(self):
        Task.objects.create(subject=self.subject, exam_version=self.source, type=self.old_types[27], slug="release-27", title="Other", description="Different", correct_answer=[9, 8], status="published")
        with self.assertRaisesMessage(ValidationError, "отличается"):
            prepare_release(self.source, files_dir=self.root, apply=True)
        self.assertEqual(ExamVersion.objects.count(), 1)
        self.assertEqual(Task.objects.count(), 28)
        self.assertFalse(TaskAttachment.objects.exists())
        self.assertFalse(any(p.is_file() for p in (self.root / "media").rglob("*")))

    def test_command_requires_explicit_database_for_writes(self):
        with self.assertRaisesMessage(CommandError, "expect-database"):
            call_command("prepare_informatics_2027_release", source_exam_slug=self.source.slug, files=self.root, apply=True)
