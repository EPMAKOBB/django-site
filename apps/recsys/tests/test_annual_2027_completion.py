from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from apps.recsys.models import (
    AnswerSchema, ExamBlueprint, ExamBlueprintItem, ExamVersion, Subject, Task, TaskPlacement,
    TaskTag, TaskType, TaskTypeTransition,
)
from apps.recsys.service_utils.exam_rollover import placement_plan, publish_exam, validate_rollover
from apps.recsys.service_utils.grading import grade_answer
from apps.recsys.service_utils.variants import _grade_answer


class AnnualPairGradingTests(SimpleTestCase):
    def test_new_pair_rubric_in_training_and_variants(self):
        for grader in (grade_answer, _grade_answer):
            for answer, expected in [
                ([539936, 100704], (2, True)),
                ([100704, 539936], (1, False)),
                ([539936, 0], (1, False)),
                ([0, 100704], (1, False)),
                ([539936], (1, False)),
                ([None, 100704], (1, False)),
                ([0, 0], (0, False)),
                ([], (0, False)),
            ]:
                with self.subTest(grader=grader.__module__, answer=answer):
                    self.assertEqual(grader("ege_pairs_2027", [539936, 100704], answer, max_score=2), expected)

    def test_previous_rubrics_keep_their_semantics(self):
        for grader in (grade_answer, _grade_answer):
            self.assertEqual(grader("partial_pairs", [10, 20], [20, 10], max_score=2), (0, False))
            self.assertEqual(grader("partial_rows", [[1, 2], [3, 4]], [[1, 2], [0, 0]], max_score=2), (1, False))
            self.assertEqual(grader("ege_pairs_2027", [10, 10], [10, 10], max_score=2), (2, True))


class ExplicitEmptySourcePoolTests(TestCase):
    def setUp(self):
        subject = Subject.objects.create(name="Informatics", slug="inf")
        self.old = ExamVersion.objects.create(subject=subject, name="2026", slug="old", status="active")
        self.new = ExamVersion.objects.create(subject=subject, name="2027", slug="new", year=2027,
            exam_kind="ege", copied_from=self.old,
            publication_info={"requirements_checked": True, "scale_checked": True, "source_document": "Test"})
        old_schema = AnswerSchema.objects.create(name="old-grid", config={"rows": 2, "cols": 2, "input_type": "uint"})
        new_schema = AnswerSchema.objects.create(name="new-pair", config={"rows": 1, "cols": 2, "input_type": "uint"})
        self.old_type = TaskType.objects.create(subject=subject, exam_version=self.old, name="27", slug="27", answer_schema=old_schema)
        self.new_type = TaskType.objects.create(subject=subject, exam_version=self.new, name="27", slug="27",
            scoring_scheme="ege_pairs_2027", max_score=2, answer_schema=new_schema)
        tag = TaskTag.objects.create(subject=subject, name="Clustering", slug="clustering")
        self.new_type.required_tags.add(tag)
        self.old_task = Task.objects.create(subject=subject, exam_version=self.old, type=self.old_type,
            title="Old", slug="old-task", description="Four numbers", correct_answer=[[1, 2], [3, 4]], status="published")
        TaskPlacement.objects.create(task=self.old_task, task_type=self.old_type, status="active")
        TaskPlacement.objects.create(task=self.old_task, task_type=self.new_type, status="draft")
        self.new_task = Task.objects.create(subject=subject, exam_version=self.new, type=self.new_type,
            title="New", slug="new-task", description="Two numbers", correct_answer=[5, 6], status="published")
        self.new_task.tags.add(tag)
        TaskPlacement.objects.create(task=self.new_task, task_type=self.new_type, status="draft")
        self.row = TaskTypeTransition.objects.create(target_exam=self.new, source_type=self.old_type,
            target_type=self.new_type, relation="partial", approved=True, notes="All old tasks use an incompatible answer format.")
        bp = ExamBlueprint.objects.create(subject=subject, exam_version=self.new)
        ExamBlueprintItem.objects.create(blueprint=bp, task_type=self.new_type, order=27)

    def test_empty_pool_requires_explicit_confirmation(self):
        self.assertTrue(placement_plan(self.new)[1])
        self.row.allow_empty_source_pool = True
        self.row.save()
        self.assertEqual(placement_plan(self.new)[1], [])
        self.assertTrue(validate_rollover(self.new)["ready"])
        publish_exam(self.new)
        self.assertEqual(TaskPlacement.objects.get(task=self.old_task, task_type=self.old_type).status, "active")
        self.assertEqual(TaskPlacement.objects.get(task=self.old_task, task_type=self.new_type).status, "retired")
        self.assertEqual(TaskPlacement.objects.get(task=self.new_task, task_type=self.new_type).status, "active")
        self.old_task.refresh_from_db()
        self.assertEqual(self.old_task.correct_answer, [[1, 2], [3, 4]])

    def test_empty_flag_cannot_hide_a_missing_split_or_explanation(self):
        self.row.allow_empty_source_pool = True
        for relation, notes, ids in [("split", "Reason", []), ("partial", "", []), ("partial", "Reason", [self.old_task.pk])]:
            self.row.relation, self.row.notes, self.row.task_ids = relation, notes, ids
            with self.subTest(relation=relation, notes=notes, ids=ids), self.assertRaises(ValidationError):
                self.row.full_clean()
