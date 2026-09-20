from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from apps.recsys.models import (
    Subject, ExamVersion, TaskType, Task, TaskTag, TaskPlacement, Attempt, TypeMastery,
    ExamBlueprint, ExamBlueprintItem, ExamScoreScale, VariantTaskAttempt, TagMastery,
    ExamProgressSnapshot, TaskTypeTransition,
)
from apps.recsys.service_utils import training, variants
from apps.recsys.service_utils.exam_context import resolve_placement, snapshot_task
from apps.recsys.service_utils.exam_history import backfill_context, exam_report
from apps.recsys.service_utils.exam_rollover import create_next_year, publish_exam, archive_exam, match_blueprint
from apps.recsys.service_utils.type_progress import build_type_progress_map
from apps.recsys.services import apply_forgetting_to_tag_masteries


class ExamYearTransitionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="annual-student")
        self.subject = Subject.objects.create(name="Информатика", slug="informatics")
        self.old = ExamVersion.objects.create(subject=self.subject, name="ЕГЭ 2026", slug="informatics-ege-2026", exam_kind="ege", year=2026, status="active")
        self.tag = TaskTag.objects.create(subject=self.subject, name="IP-сети", slug="ip-networks")
        self.old_type = TaskType.objects.create(subject=self.subject, exam_version=self.old, name="Тип 13", slug="13", display_order=13)
        self.old_type.required_tags.add(self.tag)
        self.task = Task.objects.create(subject=self.subject, type=self.old_type, exam_version=self.old, title="Сеть", slug="ip-example", description="**Исходное условие**", correct_answer={"value": "42"}, status="published")
        self.task.tags.add(self.tag)
        self.placement = resolve_placement(self.task, exam_version=self.old)
        bp = ExamBlueprint.objects.create(exam_version=self.old, subject=self.subject, time_limit=timedelta(minutes=10))
        ExamBlueprintItem.objects.create(blueprint=bp, task_type=self.old_type, order=1, count=1)
        ExamScoreScale.objects.create(exam_version=self.old, max_primary=1, mapping=[0, 100])

    def next_year(self, publish=True):
        exam = create_next_year(self.old, year=2027)
        task_type = exam.task_types.get()
        task_type.name = "Тип 10"
        task_type.slug = "10"
        task_type.display_order = 10
        task_type.save()
        if publish:
            transition = exam.type_transitions.get()
            transition.approved = True
            transition.save()
            exam.publication_info = {"requirements_checked": True, "scale_checked": True, "source_document": "Тестовая спецификация"}
            exam.save()
            exam = publish_exam(exam)
        return exam, task_type

    def answer(self, placement=None):
        placement = placement or self.placement
        task = Task.objects.get(pk=self.task.pk)
        return Attempt.objects.create(user=self.user, task=task, placement=placement,
                                      task_snapshot=snapshot_task(task, placement), is_correct=True, score=1, max_score=1)

    def test_renumbering_preserves_task_and_old_attempts(self):
        answer = self.answer()
        new, new_type = self.next_year()
        self.task.refresh_from_db()
        self.assertEqual(Task.objects.count(), 1)
        self.assertEqual(self.task.type_id, self.old_type.pk)
        self.assertEqual(self.task.placements.count(), 2)
        self.answer(self.task.placements.get(task_type=new_type))
        answer.refresh_from_db()
        self.assertEqual(answer.task_type_id, self.old_type.pk)
        self.assertEqual(answer.exam_version_id, self.old.pk)
        self.assertEqual(Attempt.objects.filter(exam_version=self.old).count(), 1)
        self.assertEqual(Attempt.objects.filter(exam_version=new).count(), 1)

    def test_previous_year_evidence_exists_before_new_attempt(self):
        self.answer()
        new, new_type = self.next_year()
        info = build_type_progress_map(user=self.user, task_type_ids=[new_type.pk])[new_type.pk]
        self.assertEqual(info.effective_mastery, 1)
        report = exam_report(self.user, new)["types"][str(new_type.pk)]
        self.assertEqual(report["attempts"], 0)
        self.assertEqual(report["previous_year_evidence"], 1)

    def test_new_requirement_remains_uncovered(self):
        self.answer()
        new, new_type = self.next_year(publish=False)
        tag = TaskTag.objects.create(subject=self.subject, name="Новая тема")
        new_type.required_tags.add(tag)
        # Draft catalogs are excluded from public readiness; explicitly activate
        # the reused task to inspect the denominator for a new requirement.
        new_type.placements.update(status="active")
        info = build_type_progress_map(user=self.user, task_type_ids=[new_type.pk])[new_type.pk]
        self.assertEqual(info.effective_mastery, 0.5)

    def test_archive_snapshot_is_immutable_after_new_year_answer(self):
        self.answer()
        new, new_type = self.next_year()
        archive_exam(self.old)
        saved = ExamProgressSnapshot.objects.get(exam_version=self.old, purpose="archive")
        original = deepcopy(saved.data)
        self.answer(self.task.placements.get(task_type=new_type))
        saved.refresh_from_db()
        self.assertEqual(saved.data, original)
        with self.assertRaises(ValidationError):
            saved.save()
        self.client.force_login(self.user)
        self.assertEqual(Attempt.objects.filter(exam_version=self.old).count(), 1)

    def test_started_training_keeps_old_context_and_each_response(self):
        session = training.start_session(self.user, exam_version=self.old)
        step = session.steps.get()
        self.next_year()
        training.submit_step_answer(self.user, session_id=session.pk, step_id=step.pk, answer={"value": "0"})
        training.submit_step_answer(self.user, session_id=session.pk, step_id=step.pk, answer={"value": "42"})
        answers = list(Attempt.objects.order_by("pk"))
        self.assertEqual(len(answers), 2)
        self.assertEqual([a.exam_version_id for a in answers], [self.old.pk, self.old.pk])
        self.assertNotEqual(answers[0].response_snapshot, answers[1].response_snapshot)
        self.assertEqual(answers[0].task_snapshot, answers[1].task_snapshot)

    def test_new_training_uses_new_type(self):
        new, new_type = self.next_year()
        session = training.start_session(self.user, exam_version=new)
        step = session.steps.get()
        self.assertEqual(step.placement.task_type_id, new_type.pk)
        training.submit_step_answer(self.user, session_id=session.pk, step_id=step.pk, answer={"value": "42"})
        self.assertEqual(Attempt.objects.get().task_type_id, new_type.pk)

    def test_variant_preserves_grading_scale_and_statement(self):
        assignment = variants.build_personal_assignment_from_blueprint(user=self.user, exam_version=self.old)
        attempt = variants.start_new_attempt(self.user, assignment.pk)
        original = variants.build_tasks_progress(attempt)[0]
        self.task.description = "Изменённое условие"
        self.task.save()
        self.old_type.max_score = 2
        self.old_type.name = "Изменённое имя"
        self.old_type.save()
        assignment.template.template_tasks.update(max_attempts=7)
        changed = variants.build_tasks_progress(attempt)[0]
        self.assertEqual(original["task_body_html"], changed["task_body_html"])
        self.assertEqual(changed["task_type_name"], "Тип 13")
        self.assertEqual(changed["max_score"], 1)
        self.assertEqual(changed["max_attempts"], original["max_attempts"])
        self.assertEqual(variants.calculate_attempt_primary_summary(attempt)["primary_max_total"], 1)
        self.assertEqual(attempt.exam_snapshot["scale"], [0, 100])

    def test_new_variant_uses_placement(self):
        new, new_type = self.next_year()
        assignment = variants.build_personal_assignment_from_blueprint(user=self.user, exam_version=new)
        self.assertEqual(assignment.template.template_tasks.get().placement.task_type_id, new_type.pk)
        attempt = variants.start_new_attempt(self.user, assignment.pk)
        context = attempt.task_attempts.get(attempt_number=0).task_snapshot["task"]["context"]
        self.assertEqual(context["task_type_id"], new_type.pk)

    def test_repeated_next_year_does_not_duplicate_objects(self):
        first, _ = self.next_year(publish=False)
        second = create_next_year(self.old, year=2027)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Task.objects.count(), 1)
        self.assertEqual(TaskPlacement.objects.count(), 2)

    def test_publication_requires_review(self):
        new, _ = self.next_year(publish=False)
        with self.assertRaises(ValidationError):
            publish_exam(new)
        new.refresh_from_db()
        self.assertEqual(new.status, "draft")

    def test_backfill_is_idempotent_and_does_not_replay_mastery(self):
        answer = self.answer()
        Attempt.objects.filter(pk=answer.pk).update(context_snapshot={}, task_snapshot={}, context_origin="unknown", task_type=None, exam_version=None, placement=None)
        before = list(TagMastery.objects.values("mastery", "attempts_total"))
        dry = backfill_context()
        self.assertEqual(dry["counts"]["inferred"], 1)
        backfill_context(apply=True)
        second = backfill_context(apply=True)
        self.assertEqual(second["counts"].get("inferred", 0), 0)
        self.assertEqual(Attempt.objects.count(), 1)
        self.assertEqual(before, list(TagMastery.objects.values("mastery", "attempts_total")))

    def test_conflicting_backfill_preserves_unknown_record(self):
        answer = self.answer()
        other = ExamVersion.objects.create(subject=self.subject, name="Другая версия")
        Task.objects.filter(pk=self.task.pk).update(exam_version=other)
        Attempt.objects.filter(pk=answer.pk).update(context_snapshot={}, task_snapshot={}, context_origin="unknown", task_type=None, exam_version=None, placement=None)
        result = backfill_context(apply=True)
        self.assertEqual(result["counts"]["unresolved"], 1)
        answer.refresh_from_db()
        self.assertEqual(answer.context_origin, "unknown")

    def test_context_cannot_be_reassigned_or_task_deleted(self):
        answer = self.answer()
        new, new_type = self.next_year()
        answer.task_type = new_type
        with self.assertRaises(ValidationError):
            answer.save()
        with self.assertRaises(ProtectedError):
            self.task.delete()

    def test_ambiguous_direct_answer_requires_placement(self):
        self.next_year()
        with self.assertRaises(ValidationError):
            Attempt.objects.create(user=self.user, task=self.task, is_correct=True)

    def test_matching_handles_overlapping_pools(self):
        selected = match_blueprint([(13, 1, [1, 2]), (10, 1, [1])])
        self.assertEqual(selected, [(13, 2), (10, 1)])
        with self.assertRaises(ValidationError):
            match_blueprint([(13, 1, [1]), (10, 1, [1])])

    def test_forgetting_is_idempotent_for_same_instant(self):
        self.answer()
        now = timezone.now() + timedelta(days=5)
        apply_forgetting_to_tag_masteries(now=now)
        before = TagMastery.objects.get().mastery
        apply_forgetting_to_tag_masteries(now=now)
        self.assertEqual(TagMastery.objects.get().mastery, before)

    def test_catalog_and_archive_views(self):
        from django.urls import reverse
        new, _ = self.next_year()
        self.client.force_login(self.user)
        response = self.client.get(reverse("exam-page", args=[new.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ЕГЭ 2027")
        self.answer()
        archive_exam(self.old)
        response = self.client.get(reverse("exam-progress-data", args=[self.old.slug]))
        self.assertTrue(response.json()["archived"])
        self.assertEqual(response.json()["annual_report"]["types"][str(self.old_type.pk)]["attempts"], 1)

    def test_training_retry_keeps_one_answer_and_hides_solution(self):
        session = training.start_session(self.user, exam_version=self.old)
        step = session.steps.get()
        self.assertNotIn("correct_answer", training.session_payload(session)["current_task"])
        key = uuid4()
        first = training.submit_step_answer(self.user, session_id=session.pk, step_id=step.pk, answer={"value": "0"}, submission_key=key)
        second = training.submit_step_answer(self.user, session_id=session.pk, step_id=step.pk, answer={"value": "0"}, submission_key=key)
        self.assertEqual(first["submission_result"]["attempt_id"], second["submission_result"]["attempt_id"])
        self.assertEqual(Attempt.objects.count(), 1)
        self.assertEqual(TagMastery.objects.get().attempts_total, 1)

    def test_variant_retry_keeps_one_record(self):
        assignment = variants.build_personal_assignment_from_blueprint(user=self.user, exam_version=self.old)
        attempt = variants.start_new_attempt(self.user, assignment.pk)
        task_id = assignment.template.template_tasks.get().pk
        key = uuid4()
        for _ in range(2):
            variants.submit_task_answer(self.user, attempt.pk, task_id, is_correct=True, task_snapshot={"value": "42"}, submission_key=key)
        self.assertEqual(attempt.task_attempts.filter(attempt_number__gt=0).count(), 1)
        self.assertEqual(Attempt.objects.count(), 1)

    def test_changed_grading_does_not_transfer_full_readiness(self):
        self.answer()
        new, task_type = self.next_year(publish=False)
        task_type.max_score = 2
        task_type.save()
        task_type.placements.update(status="active")
        progress = build_type_progress_map(user=self.user, task_type_ids=[task_type.pk])[task_type.pk]
        self.assertEqual(progress.effective_mastery, 0)
        self.assertEqual(progress.previous_year_evidence, 0)

    def test_published_requirements_are_frozen_and_revision_is_independent(self):
        new, task_type = self.next_year()
        task_type.name = "Другое имя"
        with self.assertRaises(ValidationError):
            task_type.save()
        with self.assertRaises(ValidationError), transaction.atomic():
            task_type.required_tags.clear()
        new.status = "archived"
        with self.assertRaises(ValidationError):
            new.save()
        revision = create_next_year(new, year=2027, new_revision=True)
        self.assertEqual((revision.year, revision.revision, revision.status), (2027, 2, "draft"))
        self.assertEqual(revision.pk, create_next_year(new, year=2027, new_revision=True).pk)
        self.assertEqual(Task.objects.count(), 1)

    def test_split_records_only_explicit_tasks(self):
        second_task = Task.objects.create(subject=self.subject, type=self.old_type, exam_version=self.old, title="Вторая сеть", slug="second-ip", status="published")
        second_task.tags.add(self.tag)
        resolve_placement(second_task, exam_version=self.old)
        new, first_type = self.next_year(publish=False)
        second_type = TaskType.objects.create(subject=self.subject, exam_version=new, name="Тип 11", slug="11")
        second_type.required_tags.add(self.tag)
        row = new.type_transitions.get()
        row.relation, row.task_ids, row.approved = "split", [self.task.pk], True
        row.save()
        TaskTypeTransition.objects.create(target_exam=new, source_type=self.old_type, target_type=second_type,
                                          relation="split", task_ids=[second_task.pk], approved=True)
        ExamBlueprintItem.objects.create(blueprint=new.blueprint, task_type=second_type, count=1, order=2)
        new.publication_info = {"requirements_checked": True, "scale_checked": True, "source_document": "test"}
        new.save()
        publish_exam(new)
        self.assertEqual(set(first_type.placements.filter(status="active").values_list("task_id", flat=True)), {self.task.pk})
        self.assertEqual(set(second_type.placements.filter(status="active").values_list("task_id", flat=True)), {second_task.pk})
        self.answer()
        info = build_type_progress_map(user=self.user, task_type_ids=[first_type.pk, second_type.pk])
        self.assertEqual((info[first_type.pk].effective_mastery, info[second_type.pk].effective_mastery), (1, 0))

    def test_archived_exam_allows_issued_answer_and_blocks_new_start(self):
        from rest_framework.exceptions import ValidationError as ApiError
        session = training.start_session(self.user, exam_version=self.old)
        step = session.steps.get()
        archive_exam(self.old)
        self.old.refresh_from_db()
        training.submit_step_answer(self.user, session_id=session.pk, step_id=step.pk, answer={"value": "42"})
        with self.assertRaises(ApiError):
            training.start_session(self.user, exam_version=self.old)
        self.assertEqual(Attempt.objects.get().exam_version_id, self.old.pk)

    def test_recommendation_snapshot_survives_renumbering(self):
        self.client.force_login(self.user)
        issued = self.client.get("/api/next-task/").json()
        self.assertNotIn("correct_answer", issued["issued_task"])
        self.next_year()
        key = str(uuid4())
        payload = {"task": self.task.pk, "source_recommendation": issued["recommendation_id"], "is_correct": True, "submission_key": key}
        first = self.client.post("/api/attempts/", data=payload, content_type="application/json")
        second = self.client.post("/api/attempts/", data=payload, content_type="application/json")
        self.assertEqual((first.status_code, second.status_code), (201, 201))
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(Attempt.objects.get().task_type_id, self.old_type.pk)

    def test_blueprint_score_override_is_frozen(self):
        self.old.blueprint.items.update(score_override=2)
        assignment = variants.build_personal_assignment_from_blueprint(user=self.user, exam_version=self.old)
        attempt = variants.start_new_attempt(self.user, assignment.pk)
        self.old.blueprint.items.update(score_override=3)
        self.assertEqual(variants.calculate_attempt_primary_summary(attempt)["primary_max_total"], 2)

    def test_history_files_survive_attachment_deletion(self):
        from apps.recsys.models import TaskAttachment
        from apps.recsys.service_utils.historical_files import referenced_storage_files
        attachment = TaskAttachment.objects.create(task=self.task, file="tasks/bank/original.csv")
        self.answer()
        attachment.delete()
        self.assertIn("tasks/bank/original.csv", referenced_storage_files())

    def test_progress_cutoff_ignores_later_answers(self):
        cutoff = timezone.now()
        self.answer()
        report = exam_report(self.user, self.old, as_of=cutoff)
        self.assertEqual(report["types"][str(self.old_type.pk)]["readiness"], 0)

    def test_legacy_work_backfill_keeps_content_and_marks_unknown_scale(self):
        from apps.recsys.models import VariantAttempt
        assignment = variants.build_personal_assignment_from_blueprint(user=self.user, exam_version=self.old)
        attempt = variants.start_new_attempt(self.user, assignment.pk)
        original = attempt.task_attempts.get(attempt_number=0)
        frozen = deepcopy(original.task_snapshot)
        frozen["task"].pop("context")
        frozen["task"].pop("task_body_html")
        VariantTaskAttempt.objects.filter(pk=original.pk).update(task_snapshot=frozen)
        VariantAttempt.objects.filter(pk=attempt.pk).update(exam_snapshot={})
        self.task.description = "Текст после выдачи"
        self.task.save()
        result = backfill_context(apply=True)
        self.assertEqual(result["counts"]["legacy_work_snapshots"], 1)
        attempt.refresh_from_db()
        self.assertTrue(attempt.exam_snapshot["scale_unknown"])
        self.assertIsNone(attempt.exam_snapshot["scale"])
        self.assertIn("Исходное условие", variants.build_tasks_progress(attempt)[0]["task_body_html"])
        second = backfill_context(apply=True)
        self.assertEqual(second["counts"].get("legacy_work_snapshots", 0), 0)

    def test_admin_publishes_reviewed_draft_and_keeps_published_forms_readable(self):
        from django.urls import reverse
        admin_user = get_user_model().objects.create_superuser(username="annual-admin", password="test-password")
        self.client.force_login(admin_user)
        response = self.client.post(reverse("admin:recsys_examversion_next_year", args=[self.old.pk]), {"year": 2027, "exam_kind": "ege"})
        self.assertEqual(response.status_code, 302)
        new = ExamVersion.objects.get(copied_from=self.old)
        row = new.type_transitions.get()
        row.approved = True
        row.save()
        response = self.client.post(reverse("admin:recsys_examversion_review_year", args=[new.pk]), {
            "action": "publish", "source_document": "Тестовая спецификация", "requirements_checked": "on", "scale_checked": "on",
        })
        self.assertEqual(response.status_code, 302)
        new.refresh_from_db()
        self.assertEqual(new.status, "active")
        for name, pk in [("examversion", new.pk), ("tasktype", new.task_types.get().pk), ("examblueprint", new.blueprint.pk)]:
            response = self.client.get(reverse(f"admin:recsys_{name}_change", args=[pk]))
            self.assertEqual(response.status_code, 200)

    def test_draft_cannot_be_used_for_new_training(self):
        from rest_framework.exceptions import ValidationError as ApiError
        new, _ = self.next_year(publish=False)
        with self.assertRaises(ApiError):
            training.start_session(self.user, exam_version=new)

    def test_merge_projects_old_evidence_without_copying_attempts(self):
        other_type = TaskType.objects.create(subject=self.subject, exam_version=self.old, name="Тип 14", slug="14")
        tag = TaskTag.objects.create(subject=self.subject, name="Кодирование", slug="encoding")
        other_type.required_tags.add(tag)
        other_task = Task.objects.create(subject=self.subject, type=other_type, exam_version=self.old, title="Encoding", status="published")
        other_task.tags.add(tag)
        other_placement = resolve_placement(other_task, exam_version=self.old)
        self.answer()
        Attempt.objects.create(user=self.user, task=other_task, task_snapshot=snapshot_task(other_task, other_placement), is_correct=True, score=1)
        new = ExamVersion.objects.create(subject=self.subject, name="ЕГЭ 2027", slug="merge-2027", year=2027, exam_kind="ege", copied_from=self.old,
                                         publication_info={"requirements_checked": True, "scale_checked": True, "source_document": "test"})
        merged = TaskType.objects.create(subject=self.subject, exam_version=new, name="Тип 10", slug="10")
        merged.required_tags.add(self.tag, tag)
        bp = ExamBlueprint.objects.create(subject=self.subject, exam_version=new)
        ExamBlueprintItem.objects.create(blueprint=bp, task_type=merged, count=2)
        for source, task in [(self.old_type, self.task), (other_type, other_task)]:
            TaskTypeTransition.objects.create(target_exam=new, source_type=source, target_type=merged,
                                              relation="merge", task_ids=[task.pk], approved=True)
        publish_exam(new)
        report = exam_report(self.user, new)["types"][str(merged.pk)]
        self.assertEqual((report["attempts"], report["previous_year_evidence"], report["readiness"]), (0, 2, 1))
        self.assertEqual(Attempt.objects.count(), 2)

    def test_rebuild_matches_online_state_and_is_repeatable(self):
        from apps.recsys.services import refresh_student_recsys_state
        from apps.recsys.service_utils.rebuild_learning import rebuild_learning_state
        self.answer()
        new, task_type = self.next_year()
        self.answer(self.task.placements.get(task_type=task_type))
        now = timezone.now() + timedelta(days=3)
        refresh_student_recsys_state(self.user, now=now)
        fields = ["mastery", "coverage", "progress", "confidence", "stability", "attempts_total", "successes_total"]
        before = list(TagMastery.objects.values(*fields))
        for _ in range(2):
            rebuild_learning_state(self.user, now=now)
            self.assertEqual(before, list(TagMastery.objects.values(*fields)))
        self.assertEqual(Attempt.objects.count(), 2)

    def test_default_change_preserves_student_target_and_open_session(self):
        from accounts.models import StudentProfile
        profile, _ = StudentProfile.objects.get_or_create(user=self.user)
        profile.exam_versions.add(self.old)
        session = training.start_session(self.user, exam_version=self.old)
        new, _ = self.next_year(publish=False)
        row = new.type_transitions.get()
        row.approved = True
        row.save()
        new.publication_info = {"requirements_checked": True, "scale_checked": True, "source_document": "test"}
        new.save()
        publish_exam(new, make_default=True)
        self.assertEqual(list(profile.exam_versions.values_list("pk", flat=True)), [self.old.pk])
        session.refresh_from_db()
        self.assertEqual((session.exam_version_id, session.status), (self.old.pk, "active"))
        from apps.recsys.recommendation import recommend_task_candidates
        candidate = recommend_task_candidates(self.user, limit=1, log=False, exclude_recent=False)[0]
        self.assertEqual(candidate.task.selected_placement.task_type.exam_version_id, self.old.pk)
        newcomer = get_user_model().objects.create_user(username="new-year-student")
        candidate = recommend_task_candidates(newcomer, limit=1, log=False, exclude_recent=False)[0]
        self.assertEqual(candidate.task.selected_placement.task_type.exam_version_id, new.pk)

    def test_student_can_explicitly_choose_a_year(self):
        from django.urls import reverse
        from accounts.models import StudentProfile
        new, _ = self.next_year()
        self.client.force_login(self.user)
        url = reverse("exam-page", args=[new.slug])
        self.assertEqual(self.client.post(url, {"action": "select_year"}).status_code, 302)
        profile = StudentProfile.objects.get(user=self.user)
        self.assertTrue(profile.exam_versions.filter(pk=new.pk).exists())
        self.assertEqual(self.client.post(url, {"action": "unselect_year"}).status_code, 302)
        self.assertFalse(profile.exam_versions.filter(pk=new.pk).exists())

    def test_calendar_filter_does_not_change_current_readiness(self):
        from django.urls import reverse
        self.answer()
        self.client.force_login(self.user)
        url = reverse("exam-progress-data", args=[self.old.slug])
        response = self.client.get(url, {"from": "2030-01-01", "to": "2030-01-31"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["period_history"]["types"], [])
        self.assertEqual(response.json()["annual_report"]["types"][str(self.old_type.pk)]["readiness"], 1)
        self.assertEqual(self.client.get(url, {"from": "invalid"}).status_code, 400)

    def test_task_editor_adds_annual_binding_without_reassigning_task(self):
        import json
        from apps.recsys.forms import TaskUploadForm
        new, task_type = self.next_year(publish=False)
        form = TaskUploadForm(data={"subject": self.subject.pk, "exam_version": self.old.pk, "type": self.old_type.pk,
            "title": self.task.title, "slug": self.task.slug, "description": self.task.description, "status": "published",
            "rendering_strategy": self.task.rendering_strategy, "difficulty_level": 0,
            "correct_answer": json.dumps(self.task.correct_answer), "tags": [self.tag.pk],
            "additional_types": [task_type.pk], "manage_placements": "1"}, instance=self.task)
        self.assertTrue(form.is_valid(), form.errors)
        form.create_task_with_attachments()
        self.task.refresh_from_db()
        self.assertEqual(self.task.type_id, self.old_type.pk)
        self.assertEqual(self.task.placements.count(), 2)
        self.assertEqual(Task.objects.count(), 1)

    def test_later_template_task_is_excluded_from_old_work(self):
        from apps.recsys.models import VariantTask
        from rest_framework.exceptions import ValidationError as ApiError
        assignment = variants.build_personal_assignment_from_blueprint(user=self.user, exam_version=self.old)
        attempt = variants.start_new_attempt(self.user, assignment.pk)
        task = Task.objects.create(subject=self.subject, type=self.old_type, exam_version=self.old, title="Later task", status="published")
        # Reproduce old data from before the model guards existed.
        VariantTask.objects.bulk_create([VariantTask(template=assignment.template, task=task, order=2)])
        extra = assignment.template.template_tasks.get(task=task)
        self.assertEqual(len(variants.build_tasks_progress(attempt)), 1)
        self.assertEqual(variants.calculate_assignment_progress(assignment)["total_tasks"], 1)
        with self.assertRaises(ApiError):
            variants.submit_task_answer(self.user, attempt.pk, extra.pk, is_correct=True)

    def test_reviewed_new_scale_does_not_change_old_work(self):
        old_assignment = variants.build_personal_assignment_from_blueprint(user=self.user, exam_version=self.old)
        old_attempt = variants.start_new_attempt(self.user, old_assignment.pk)
        new, _ = self.next_year(publish=False)
        scale = new.score_scale
        scale.mapping, scale.is_active = [0, 90], True
        scale.save()
        row = new.type_transitions.get()
        row.approved = True
        row.save()
        new.publication_info = {"requirements_checked": True, "scale_checked": True, "source_document": "test"}
        new.save()
        new = publish_exam(new)
        new_assignment = variants.build_personal_assignment_from_blueprint(user=self.user, exam_version=new)
        new_attempt = variants.start_new_attempt(self.user, new_assignment.pk)
        old_attempt.refresh_from_db()
        self.assertEqual(old_attempt.exam_snapshot["scale"], [0, 100])
        self.assertEqual(new_attempt.exam_snapshot["scale"], [0, 90])


from django.test import TransactionTestCase
from django.db import connection, connections
from unittest import skipUnless


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks")
class AnnualConcurrencyTests(TransactionTestCase):
    setUp = ExamYearTransitionTests.setUp

    def test_parallel_answers_do_not_lose_aggregate_updates(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        gate = Barrier(2)
        frozen = snapshot_task(self.task, self.placement)

        def submit(_):
            connections.close_all()
            try:
                cached_task = Task.objects.get(pk=self.task.pk)
                gate.wait(timeout=10)
                return Attempt.objects.create(user_id=self.user.pk, task=cached_task,
                                              task_snapshot=deepcopy(frozen), is_correct=True, score=1, max_score=1).pk
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(submit, range(2)))
        self.assertEqual(len(set(result)), 2)
        self.assertEqual(TagMastery.objects.get().attempts_total, 2)
        self.task.refresh_from_db()
        self.assertEqual(self.task.attempts_total, 2)

    def test_parallel_training_retry_creates_one_answer(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        session = training.start_session(self.user, exam_version=self.old)
        step = session.steps.get()
        key, gate = uuid4(), Barrier(2)

        def submit(_):
            connections.close_all()
            try:
                user = get_user_model().objects.get(pk=self.user.pk)
                gate.wait(timeout=10)
                return training.submit_step_answer(user, session_id=session.pk, step_id=step.pk,
                                                   answer={"value": "42"}, submission_key=key)["submission_result"]["attempt_id"]
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(submit, range(2)))
        self.assertEqual(len(set(result)), 1)
        self.assertEqual(Attempt.objects.count(), 1)
