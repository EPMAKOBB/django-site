"""The requested 2026 -> 2027 permutation, with synthetic student data only."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.exceptions import ValidationError as APIValidationError

from apps.recsys.models import (
    Attempt, ExamBlueprint, ExamBlueprintItem, ExamScoreScale, ExamVersion,
    Subject, Task, TaskPlacement, TaskTag, TaskType, TaskTypeTransition,
)
from apps.recsys.service_utils import training, variants
from apps.recsys.service_utils.exam_context import resolve_placement, snapshot_task
from apps.recsys.service_utils.exam_history import capture_progress, attempt_history
from apps.recsys.service_utils.exam_rollover import create_next_year, placement_plan, publish_exam, validate_rollover
from apps.recsys.service_utils.type_progress import build_type_progress_map
from scripts.prepare_informatics_2027 import prepare_transition, retained_data_fingerprint


class Informatics2027ScenarioTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="inf-transition-student")
        self.subject = Subject.objects.create(name="Информатика", slug="inf")
        self.source = ExamVersion.objects.create(subject=self.subject, name="ЕГЭ 2026", slug="inf-ege-2026", year=2026, exam_kind="ege", status="active")
        self.bp = ExamBlueprint.objects.create(exam_version=self.source, subject=self.subject, time_limit=timedelta(minutes=30))
        ExamScoreScale.objects.create(exam_version=self.source, max_primary=4, mapping=[0, 25, 50, 75, 100])
        self.types, self.tasks = {}, {}
        for number, title, tag_names in (
            (10, "Поиск символов в текстовом редакторе", ["Поиск слова"]),
            (13, "IP-адресация компьютерных сетей", ["Количество адресов"]),
            (23, "Ветвление и перебор вариантов", ["Задачи на увеличение", "Задачи на уменьшение", "Обязательные числа", "Избегаемые числа"]),
            (27, "Кластеризация", ["Кластеризация"]),
        ):
            typ = TaskType.objects.create(subject=self.subject, exam_version=self.source, name=f"тип {number}", slug=str(number), display_order=number, description=title)
            task = Task.objects.create(subject=self.subject, exam_version=self.source, type=typ, title=title, slug=f"source-{number}", description=f"Старое условие {number}", correct_answer={"value": "42"}, status="published")
            for i, name in enumerate(tag_names):
                tag = TaskTag.objects.create(subject=self.subject, name=name, slug=f"tag-{number}-{i}")
                typ.required_tags.add(tag)
                task.tags.add(tag)
            resolve_placement(task, exam_version=self.source)
            ExamBlueprintItem.objects.create(blueprint=self.bp, task_type=typ, order=number)
            self.types[number], self.tasks[number] = typ, task
        for number in (10, 13, 23):
            task = self.tasks[number]
            placement = task.placements.get()
            Attempt.objects.create(user=self.user, task=task, placement=placement, task_snapshot=snapshot_task(task, placement), is_correct=True, score=1, max_score=1)

    def prepare(self):
        return prepare_transition(self.source, source_document="Локальный тест сценария; не методическое подтверждение.")

    def make_test_publishable(self, target):
        # These fixtures only exercise issuance after the missing content has
        # been supplied. They must never be loaded into the user's real bank.
        executor, graph = (target.task_types.get(slug=s) for s in ("13", "23"))
        graph_tag = TaskTag.objects.create(subject=self.subject, name="Тестовая тема графов", slug="test-graph")
        graph.required_tags.add(graph_tag)
        digit_tag = executor.required_tags.get(name="Замена цифр")
        for typ, tag in ((executor, digit_tag), (graph, graph_tag)):
            task = Task.objects.create(subject=self.subject, exam_version=target, type=typ, title=f"Тест {typ.slug}", slug=f"fixture-{typ.slug}", description="Только тестовая задача", correct_answer={"value": "7"}, status="published")
            task.tags.add(tag)
            TaskPlacement.objects.create(task=task, task_type=typ, status="draft")
        target.publication_info.update(requirements_checked=True, scale_checked=True)
        target.save()
        return publish_exam(target)

    def test_permutation_preserves_all_facts_and_source_bank(self):
        old_report = capture_progress(self.user, self.source)
        # Snapshot creation itself is intentional; compare after that creation.
        before = retained_data_fingerprint(self.source)
        target = self.prepare()
        self.assertEqual(before, retained_data_fingerprint(self.source))
        plan, errors = placement_plan(target)
        self.assertEqual(errors, [])
        network, executor, graph = (target.task_types.get(slug=s) for s in ("10", "13", "23"))
        self.assertEqual(plan[network.pk], {self.tasks[13].pk})
        self.assertEqual(plan[executor.pk], {self.tasks[23].pk})
        self.assertFalse(plan[graph.pk])
        self.assertFalse(TaskPlacement.objects.filter(task=self.tasks[10], task_type__exam_version=target).exists())
        self.assertEqual(set(network.required_tags.all()), set(self.types[13].required_tags.all()))
        self.assertEqual(set(executor.required_tags.values_list("name", flat=True)), set(self.types[23].required_tags.values_list("name", flat=True)) | {"Замена цифр"})
        self.assertEqual(target.type_transitions.get(source_type=self.types[10]).relation, "removed")
        self.assertEqual(target.type_transitions.get(source_type=self.types[23]).relation, "partial")
        self.assertEqual(target.type_transitions.get(target_type=graph).relation, "added")
        self.assertEqual(list(target.blueprint.items.values_list("order", "task_type__slug")), [(10, "10"), (13, "13"), (23, "23"), (27, "27")])
        old_report.refresh_from_db()
        self.assertEqual(old_report.data["types"][str(self.types[10].pk)]["attempts"], 1)
        self.assertEqual(Attempt.objects.filter(exam_version=target).count(), 0)
        self.assertEqual(Task.objects.count(), 4)

    def test_repeat_does_not_duplicate_or_change_prepared_draft(self):
        target = self.prepare()
        counts = [model.objects.count() for model in (Task, TaskType, TaskTag, TaskPlacement, TaskTypeTransition, Attempt)]
        changed_at = target.updated_at
        again = self.prepare()
        self.assertEqual(again.pk, target.pk)
        self.assertEqual(again.updated_at, changed_at)
        self.assertEqual(counts, [model.objects.count() for model in (Task, TaskType, TaskTag, TaskPlacement, TaskTypeTransition, Attempt)])

    def test_incomplete_graph_has_zero_coverage_and_blocks_publication(self):
        target = self.prepare()
        graph = target.task_types.get(slug="23")
        progress = build_type_progress_map(user=self.user, task_type_ids=[graph.pk])[graph.pk]
        self.assertEqual(progress.effective_mastery, 0)
        self.assertEqual(progress.coverage_ratio, 0)
        self.assertEqual(progress.previous_year_evidence, 0)
        report = validate_rollover(target)
        self.assertFalse(report["ready"])
        self.assertTrue(any("Замена цифр" in error for error in report["errors"]))
        self.assertTrue(any("тип 23" in error for error in report["errors"]))
        with self.assertRaises(ValidationError):
            publish_exam(target)
        target.refresh_from_db()
        self.assertEqual(target.status, "draft")
        self.assertIsNone(target.published_at)
        with self.assertRaises(APIValidationError):
            training.start_session(self.user, exam_version=target)

    def test_issued_old_work_and_new_year_readiness_after_completed_test_bank(self):
        old_assignment = variants.build_personal_assignment_from_blueprint(user=self.user, exam_version=self.source)
        old_work = variants.start_new_attempt(self.user, old_assignment.pk)
        old_manifest = old_work.exam_snapshot
        old_progress = variants.build_tasks_progress(old_work)
        old_history = attempt_history(self.user, self.source)
        target = self.make_test_publishable(self.prepare())
        network, executor, graph = (target.task_types.get(slug=s) for s in ("10", "13", "23"))
        progress = build_type_progress_map(user=self.user, task_type_ids=[network.pk, executor.pk, graph.pk])
        self.assertEqual(progress[network.pk].effective_mastery, 1)
        self.assertEqual(progress[executor.pk].effective_mastery, 0.8)
        self.assertEqual(progress[graph.pk].effective_mastery, 0)
        self.assertEqual(progress[graph.pk].previous_year_evidence, 0)
        digit = next(row for row in progress[executor.pk].tag_progress if row.tag.name == "Замена цифр")
        self.assertEqual(digit.solved_count, 0)
        self.assertEqual(attempt_history(self.user, self.source), old_history)
        old_work.refresh_from_db()
        self.assertEqual(old_work.exam_snapshot, old_manifest)
        self.assertEqual(variants.build_tasks_progress(old_work), old_progress)
        assignment = variants.build_personal_assignment_from_blueprint(user=self.user, exam_version=target)
        work = variants.start_new_attempt(self.user, assignment.pk)
        issued = variants.build_tasks_progress(work)
        self.assertEqual(len(issued), 4)
        self.assertEqual(len({row["task_id"] for row in issued}), 4)
        self.assertNotIn(self.tasks[10].pk, {row["task_id"] for row in issued})
        row = next(row for row in issued if row["task_snapshot"]["context"]["task_type_id"] == network.pk)
        self.assertEqual(row["task_id"], self.tasks[13].pk)
        variants.submit_task_answer(self.user, work.pk, row["variant_task_id"], is_correct=True, task_snapshot={"value": "42"})
        self.assertEqual(Attempt.objects.filter(exam_version=target, task_type=network).count(), 1)
        self.assertEqual(attempt_history(self.user, self.source), old_history)

    def test_existing_manual_edits_are_not_overwritten(self):
        target = create_next_year(self.source, year=2027)
        typ = target.task_types.get(slug="10")
        typ.description = "Правка методиста"
        typ.save()
        with self.assertRaisesMessage(ValidationError, "уже изменены"):
            self.prepare()
        typ.refresh_from_db()
        self.assertEqual(typ.description, "Правка методиста")
        self.assertFalse(TaskTag.objects.filter(name="Замена цифр").exists())

    def test_old_and_new_training_keep_their_own_executor_type(self):
        learner = get_user_model().objects.create_user(username="training-transition")
        old_session = training.start_session(learner, exam_version=self.source, selected_task_type_ids=[self.types[23].pk])
        old_step = old_session.steps.get()
        target = self.make_test_publishable(self.prepare())
        executor = target.task_types.get(slug="13")
        training.submit_step_answer(learner, session_id=old_session.pk, step_id=old_step.pk, answer={"value": "42"})
        old_answer = Attempt.objects.get(user=learner)
        self.assertEqual(old_answer.task_type_id, self.types[23].pk)
        self.assertEqual(old_answer.exam_version_id, self.source.pk)
        new_session = training.start_session(learner, exam_version=target, selected_task_type_ids=[executor.pk])
        new_step = new_session.steps.get()
        self.assertEqual(new_step.placement.task_type_id, executor.pk)
        training.submit_step_answer(learner, session_id=new_session.pk, step_id=new_step.pk, answer=new_step.task_snapshot["correct_answer"])
        self.assertEqual(Attempt.objects.filter(user=learner, exam_version=target, task_type=executor).count(), 1)
        old_answer.refresh_from_db()
        self.assertEqual(old_answer.task_type_id, self.types[23].pk)
