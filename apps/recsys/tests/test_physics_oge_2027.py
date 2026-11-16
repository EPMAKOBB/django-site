import io
import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.recsys.answer_rules import validate_digit_reference
from apps.recsys.forms import TaskUploadForm, compare_answers
from apps.recsys.models import (Subject, ExamVersion, TaskType, TaskTag, Task,
    ExamBlueprint, ExamBlueprintItem, ExamScoreScale, SourceVariant,
    VariantTemplate, VariantTask, VariantAssignment)
from apps.recsys.service_utils.grading import grade_answer
from apps.recsys.service_utils.exam_rollover import create_next_year, validate_rollover
from apps.recsys.service_utils import variants


def paper(text):
    return list(text) + [''] * (17 - len(text))


class OgeGradingTests(SimpleTestCase):
    def test_paper_rows_preserve_partial_credit_numbers_and_interior_errors(self):
        for rule, expected, actual, maximum, score in [
            ('ordered_one_error', paper('345'), paper('349'), 2, 1),
            ('ordered_one_error', paper('345'), paper('3 5'), 2, 0),
            ('unordered_two_partial', paper('13'), paper('31'), 2, 2),
            ('unordered_two_partial', paper('13'), paper('3'), 2, 1),
            ('unordered_two_partial', paper('13'), paper('135'), 2, 0),
            ('binary', paper('-2,5'), paper('-2.5'), 1, 1),
            ('binary', 2.5, paper('2,5'), 1, 1),
            ('binary', paper('4'), paper('5'), 1, 0),
            ('binary', paper('СЛОВО'), paper('слово'), 1, 1),
        ]:
            with self.subTest(rule=rule, actual=actual):
                self.assertEqual(grade_answer(rule, expected, actual, max_score=maximum), (score, score == maximum))

    def test_ordered_sequences_use_all_positions_and_exact_length(self):
        cases = [
            ('345', '345', 2), ('345', '349', 1), ('345', '354', 0),
            ('345', '34', 0), ('345', '3451', 0), ('345', '', 0),
            ('12', '21', 0), ('7254', '7253', 1), ('7254', '7254', 2),
            ('101', '101', 2), ('101', '111', 1),
            (['3', '4', '5'], [3, 4, 9], 1), ({'value': '345'}, ['3', '4', '5'], 2),
            ('345', ['3', '4', ''], 0), ('345', ['3', '4', None], 0),
            ('345', '3 45', 0), ('345', '３４５', 0), ('345', True, 0),
            ('345', {'value': '345', 'extra': 1}, 0), ('345', [3, 45], 0),
        ]
        for expected, actual, score in cases:
            with self.subTest(expected=expected, actual=actual):
                self.assertEqual(grade_answer('ordered_one_error', expected, actual, max_score=2), (score, score == 2))

    def test_unordered_two_grants_one_point_for_a_single_correct_choice(self):
        cases = [('13', 2), ('31', 2), ('15', 1), ('3', 1), ('1', 1),
            ('5', 0), ('45', 0), ('135', 0), ('11', 0), ('33', 0), ('', 0),
            (['1', ''], 1), (['', '3'], 1), ([' ', 3], 1), (['', ''], 0), ([1, 3], 2),
            ([1, 3, ''], 0), ([1, 1], 0), ([True, 3], 0), (13.0, 0),
            ({'value': '31'}, 2), ({'other': '13'}, 0)]
        for answer, score in cases:
            with self.subTest(answer=answer):
                self.assertEqual(grade_answer('unordered_two_partial', '13', answer, max_score=2), (score, score == 2))

    def test_invalid_references_and_maxima_are_configuration_errors(self):
        for scheme, answer, maximum in [
            ('ordered_one_error', '', 2), ('ordered_one_error', 'ab', 2),
            ('ordered_one_error', '345', 3), ('unordered_two_partial', '11', 2),
            ('unordered_two_partial', '1', 2), ('unordered_two_partial', [1, True], 2)]:
            with self.subTest(scheme=scheme, answer=answer):
                with self.assertRaises(ValueError):
                    validate_digit_reference(scheme, answer, maximum)

    def test_old_rules_and_decimal_answers_stay_compatible(self):
        self.assertEqual(grade_answer('partial_pairs', [1, 2], [2, 1], max_score=2), (1, False))
        self.assertEqual(grade_answer('binary', 2.5, '2,5', max_score=1), (1, True))
        self.assertEqual(grade_answer('binary', 2.5, '2.5', max_score=1), (1, True))
        self.assertEqual(grade_answer('manual_scaled', '', 'solution', max_score=3), (None, None))


class PhysicsPreparationTests(TestCase):
    def test_adopts_only_unused_first_type_and_preserves_author_labels(self):
        first = TaskType.objects.create(subject=self.subject, exam_version=self.exam,
            name='My first type', slug='type-1', description='My author description',
            display_order=1, max_score=2)
        options = {'adopt_existing_first_type': True, 'apply': True,
                   'expect_database': connection.settings_dict['NAME'], 'stdout': io.StringIO()}
        call_command('prepare_physics_oge_2027', **options)
        first.refresh_from_db()
        self.assertEqual((first.name, first.slug, first.description), ('My first type', 'type-1', 'My author description'))
        self.assertEqual(first.scoring_scheme, 'ordered_one_error')
        self.assertEqual(first.answer_schema.name, 'test_part_17_chars')
        self.assertEqual(self.exam.task_types.count(), 22)
        self.prepare()
        call_command('update_physics_oge_2027_final', apply=True,
            expect_database=connection.settings_dict['NAME'], stdout=io.StringIO())
        first.refresh_from_db()
        self.assertEqual(first.description, 'My author description')
        self.assertEqual(self.exam.task_types.get(display_order=1).pk, first.pk)

    def test_adoption_refuses_existing_tasks_and_rolls_back(self):
        from apps.recsys.models import AnswerSchema
        first = TaskType.objects.create(subject=self.subject, exam_version=self.exam,
            name='Existing', display_order=1,
            answer_schema=AnswerSchema.objects.create(name='single', config={'rows': 1, 'cols': 1}))
        Task.objects.create(subject=self.subject, exam_version=self.exam, type=first,
            title='Authored question', slug='authored-question', correct_answer={'value': 1})
        with self.assertRaises(CommandError):
            call_command('prepare_physics_oge_2027', adopt_existing_first_type=True, apply=True,
                expect_database=connection.settings_dict['NAME'], stdout=io.StringIO())
        self.assertEqual(self.exam.task_types.count(), 1)
        first.refresh_from_db()
        self.assertEqual(first.scoring_scheme, 'binary')

    def test_final_update_imports_draft_and_repeats_without_overwriting(self):
        self.prepare()
        out = io.StringIO()
        call_command('update_physics_oge_2027_final', stdout=out)
        self.assertFalse(Task.objects.filter(slug='fipi-phys-oge-2027-demo-17-lever').exists())
        options = {'apply': True, 'expect_database': connection.settings_dict['NAME'], 'stdout': io.StringIO()}
        call_command('update_physics_oge_2027_final', **options)
        task = Task.objects.get(slug='fipi-phys-oge-2027-demo-17-lever')
        self.assertEqual(task.status, 'draft')
        self.assertEqual(task.get_max_score(), 3)
        self.assertEqual(task.placements.get().status, 'draft')
        self.assertIn('0,35', task.reference_solution)
        self.assertIn('(3,5 ± 0,3)', task.assessment_criteria)
        self.assertFalse(self.exam.task_types.get(display_order=16).allowed_tags.filter(slug__startswith='phys-oge-topic-4-').exists())
        call_command('update_physics_oge_2027_final', **options)
        self.assertEqual(Task.objects.filter(slug=task.slug).count(), 1)
        self.prepare()
        task.reference_solution = 'Author solution'
        task.save()
        with self.assertRaises(CommandError):
            call_command('update_physics_oge_2027_final', **options)
        task.refresh_from_db()
        self.assertEqual(task.reference_solution, 'Author solution')

    def test_final_update_transitions_legacy_fingerprint_and_preserves_points(self):
        self.prepare()
        from pathlib import Path
        from django.conf import settings
        from apps.recsys.management.commands.update_physics_oge_2027_final import LEGACY_FINGERPRINT, LEGACY_SOURCE
        from apps.recsys.management.commands.prepare_physics_oge_2027 import type_description, exam_start_info
        self.exam.refresh_from_db()
        info = dict(self.exam.publication_info)
        info.update(physics_oge_preparation=LEGACY_FINGERPRINT, source_document=LEGACY_SOURCE)
        self.exam.publication_info = info
        self.exam.start_info = exam_start_info(approved=False)
        self.exam.save()
        source = self.exam.sources.get()
        source.description = LEGACY_SOURCE
        source.save()
        data = json.loads((Path(settings.BASE_DIR) / 'scripts/data/physics_oge_2027.json').read_text(encoding='utf-8'))
        for item in data['types']:
            if item['number'] == 16:
                item['sections'] = [1, 2, 3, 4]
            TaskType.objects.filter(exam_version=self.exam, display_order=item['number']).update(description=type_description(item, approved=False))
        t16 = self.exam.task_types.get(display_order=16)
        t16.required_tags.add(TaskTag.objects.get(slug='phys-oge-section-4'))
        t16.allowed_tags.add(*TaskTag.objects.filter(slug__startswith='phys-oge-topic-4-'))
        before = list(self.exam.task_types.values_list('pk', 'scoring_scheme', 'max_score'))
        call_command('update_physics_oge_2027_final', apply=True, expect_database=connection.settings_dict['NAME'], stdout=io.StringIO())
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.publication_info['document_status'], 'approved')
        self.assertNotEqual(self.exam.publication_info['physics_oge_preparation'], LEGACY_FINGERPRINT)
        self.assertEqual(list(self.exam.task_types.values_list('pk', 'scoring_scheme', 'max_score')), before)
        self.prepare()

    def test_final_update_requires_database_and_refuses_published_catalog(self):
        self.prepare()
        with self.assertRaises(CommandError):
            call_command('update_physics_oge_2027_final', apply=True, stdout=io.StringIO())
        ExamVersion.objects.filter(pk=self.exam.pk).update(published_at=timezone.now())
        with self.assertRaises(CommandError):
            call_command('update_physics_oge_2027_final', apply=True, expect_database=connection.settings_dict['NAME'], stdout=io.StringIO())
        self.assertFalse(Task.objects.exists())

    def test_schema_cleanup_previews_and_keeps_schemas_used_elsewhere(self):
        self.prepare()
        from apps.recsys.models import AnswerSchema
        from apps.recsys.paper_schemas import LEGACY_PHYSICS_SCHEMAS
        old = AnswerSchema.objects.create(name='Физика ОГЭ 2027: 3 цифры по порядку',
            config={'rows': 1, **LEGACY_PHYSICS_SCHEMAS['3 цифры по порядку']})
        task_type = self.exam.task_types.get(display_order=1)
        task_type.answer_schema = old
        task_type.save()
        other = TaskType.objects.create(subject=self.subject, name='Other catalog', answer_schema=old)
        call_command('simplify_physics_answer_schemas', stdout=io.StringIO())
        task_type.refresh_from_db()
        self.assertEqual(task_type.answer_schema_id, old.pk)
        call_command('simplify_physics_answer_schemas', apply=True,
            expect_database=connection.settings_dict['NAME'], stdout=io.StringIO())
        task_type.refresh_from_db(); other.refresh_from_db()
        self.assertEqual(task_type.answer_schema.name, 'test_part_17_chars')
        self.assertEqual(other.answer_schema_id, old.pk)
        self.assertTrue(AnswerSchema.objects.filter(pk=old.pk).exists())
        other.delete()
        call_command('simplify_physics_answer_schemas', apply=True,
            expect_database=connection.settings_dict['NAME'], stdout=io.StringIO())
        self.assertFalse(AnswerSchema.objects.filter(pk=old.pk).exists())
        self.prepare()  # The preparation command must not recreate retired forms.
        self.assertFalse(AnswerSchema.objects.filter(name__startswith='Физика ОГЭ 2027:').exists())

    def setUp(self):
        self.subject = Subject.objects.create(name='Физика', slug='phys')
        self.exam = ExamVersion.objects.create(subject=self.subject, name='ОГЭ 2027',
            slug='phys-oge-2027', exam_kind='ОГЭ', year=2027, status='active')

    def prepare(self, apply=True):
        call_command('prepare_physics_oge_2027', apply=apply,
            expect_database=connection.settings_dict['NAME'] if apply else None, stdout=io.StringIO())

    def test_preview_rolls_back_and_apply_requires_explicit_database(self):
        self.prepare(apply=False)
        self.assertFalse(self.exam.task_types.exists())
        self.assertFalse(TaskTag.objects.exists())
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.exam_kind, 'ОГЭ')
        with self.assertRaises(CommandError):
            call_command('prepare_physics_oge_2027', apply=True, stdout=io.StringIO())

    def test_prepares_draft_22_positions_39_points_and_83_topics_idempotently(self):
        self.prepare()
        self.exam.refresh_from_db()
        self.assertEqual((self.exam.exam_kind, self.exam.status), ('oge', 'draft'))
        self.assertIsNone(self.exam.published_at)
        self.assertFalse(self.exam.is_default)
        blueprint = self.exam.blueprint
        self.assertEqual(blueprint.time_limit.total_seconds(), 180 * 60)
        self.assertEqual(blueprint.items.count(), 22)
        self.assertEqual(sum(item.count * item.task_type.max_score for item in blueprint.items.all()), 39)
        self.assertEqual(TaskTag.objects.filter(slug__startswith='phys-oge-topic-').count(), 83)
        self.assertEqual(self.exam.task_types.get(display_order=1).allowed_tags.count(), 83)
        self.assertEqual(self.exam.task_types.get(display_order=17).allowed_tags.count(), 59)
        self.assertEqual(SourceVariant.objects.count(), 1)
        self.assertFalse(ExamScoreScale.objects.exists())
        self.assertFalse(validate_rollover(self.exam)['ready'])
        ids = list(self.exam.task_types.values_list('pk', flat=True))
        self.prepare()
        self.assertEqual(list(self.exam.task_types.values_list('pk', flat=True)), ids)
        self.assertEqual(TaskTag.objects.count(), 87)

    def test_existing_author_changes_are_not_overwritten(self):
        self.prepare()
        task_type = self.exam.task_types.get(display_order=1)
        task_type.name = 'Author title'
        task_type.save()
        with self.assertRaises(CommandError):
            self.prepare()
        task_type.refresh_from_db()
        self.assertEqual(task_type.name, 'Author title')

    def test_refuses_published_or_already_authored_exam(self):
        TaskType.objects.create(subject=self.subject, exam_version=self.exam, name='Existing type')
        with self.assertRaises(CommandError):
            self.prepare()
        self.exam.task_types.all().delete()
        ExamVersion.objects.filter(pk=self.exam.pk).update(published_at=timezone.now())
        with self.assertRaises(CommandError):
            self.prepare()

    def test_scores_and_formats_match_each_position(self):
        self.prepare()
        for n in range(1, 23):
            task_type = self.exam.task_types.get(display_order=n)
            rule = 'ordered_one_error' if n in (1, 2, 4, 12, 13) else 'unordered_two_partial' if n in (14, 16) else 'manual_scaled' if n >= 17 else 'binary'
            expected = 2 if n in (1, 2, 4, 12, 13, 14, 16, 18, 19) else 3 if n >= 17 else 1
            self.assertEqual((task_type.scoring_scheme, task_type.max_score), (rule, expected))
        self.assertTrue(self.exam.task_types.get(display_order=14).answer_schema.config['allow_blank_cells'])
        self.assertEqual(set(self.exam.task_types.filter(display_order__lte=16).values_list('answer_schema__name', flat=True)), {'test_part_17_chars'})
        self.assertEqual(set(self.exam.task_types.filter(display_order__gte=17).values_list('answer_schema__name', flat=True)), {'free_form_long'})

    def test_editor_allows_detailed_topics_without_requiring_them_for_publication(self):
        self.prepare()
        task_type = self.exam.task_types.get(display_order=1)
        tag = task_type.allowed_tags.first()
        self.assertFalse(task_type.required_tags.filter(pk=tag.pk).exists())
        form = TaskUploadForm(data={'subject': self.subject.pk, 'exam_version': self.exam.pk,
            'type': task_type.pk, 'title': 'Example', 'slug': 'example', 'description': 'Question',
            'status': 'draft', 'rendering_strategy': 'markdown', 'difficulty_level': 0,
            'correct_answer': json.dumps(paper('345')), 'tags': [tag.pk]})
        self.assertTrue(form.is_valid(), form.errors)
        bad = TaskUploadForm(data={**form.data, 'correct_answer': json.dumps(paper('3 5'))})
        self.assertFalse(bad.is_valid())

    def test_new_catalog_copies_and_freezes_allowed_topics(self):
        self.prepare()
        next_exam = create_next_year(self.exam, year=2028, exam_kind='oge')
        old_type = self.exam.task_types.get(display_order=1)
        next_type = next_exam.task_types.get(display_order=1)
        self.assertSetEqual(set(old_type.allowed_tags.values_list('pk', flat=True)),
            set(next_type.allowed_tags.values_list('pk', flat=True)))
        ExamVersion.objects.filter(pk=self.exam.pk).update(published_at=timezone.now())
        with self.assertRaises(ValidationError), transaction.atomic():
            old_type.allowed_tags.clear()
        with self.assertRaises(ValidationError), transaction.atomic():
            old_type.allowed_tags.first().allowed_for_task_types.remove(old_type)

    def test_decimal_schema_normalization_and_oge_scale_labels(self):
        self.prepare()
        task_type = self.exam.task_types.get(display_order=6)
        form = TaskUploadForm()
        self.assertEqual(form._normalize_answer_by_schema(task_type.answer_schema, paper('2,5')), paper('2,5'))
        self.assertTrue(compare_answers(2.5, '2,5'))
        for invalid in ['nan', 'inf', '-inf']:
            with self.assertRaises(ValidationError):
                form._coerce_cell('float', invalid, label='Ответ')
        scale = ExamScoreScale.objects.create(exam_version=self.exam, max_primary=39,
            mapping=[2] * 40, is_active=False, source_year=2026, is_provisional=True)
        self.assertIn('ОГЭ-2026', scale.display_label)
        self.assertNotIn('ЕГЭ', scale.display_label)

    def test_new_rules_reject_incompatible_point_overrides(self):
        self.prepare()
        task_type = self.exam.task_types.get(display_order=1)
        task_type.max_score = 3
        with self.assertRaises(ValidationError):
            task_type.full_clean()
        item = self.exam.blueprint.items.get(order=1)
        item.score_override = 3
        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_api_uses_server_owned_rules_and_preserves_them_in_issued_work(self):
        self.prepare()
        user = get_user_model().objects.create_user(username='oge-student')
        self.client.force_login(user)
        template = VariantTemplate.objects.create(name='OGE check', exam_version=self.exam)
        for n, answer in [(1, ['3', '4', '5']), (14, ['1', '3']), (6, 2.5)]:
            task_type = self.exam.task_types.get(display_order=n)
            task = Task.objects.create(subject=self.subject, exam_version=self.exam, type=task_type,
                title=f'Question {n}', slug=f'question-{n}', correct_answer=answer, status='published')
            VariantTask.objects.create(template=template, task=task, order=n)
        assignment = VariantAssignment.objects.create(template=template, user=user)
        work = variants.start_new_attempt(user, assignment.pk)
        ordered = template.template_tasks.get(order=1)
        unordered = template.template_tasks.get(order=14)
        numeric = template.template_tasks.get(order=6)
        for row, answer, score in [(ordered, ['3', '4', '9'], 1), (unordered, ['3', '1'], 2),
                                   (unordered, ['1', ''], 1), (numeric, '2,5', 1)]:
            response = self.client.post(f'/api/variants/attempts/{work.pk}/tasks/{row.pk}/submit/',
                json.dumps({'is_correct': True, 'task_snapshot': {'value': answer}}), content_type='application/json')
            self.assertEqual(response.status_code, 201, response.content)
            latest = work.task_attempts.filter(variant_task=row, attempt_number__gt=0).latest('attempt_number')
            self.assertEqual(latest.score, score)
        # A later draft edit must not change the rule of an already issued task.
        TaskType.objects.filter(pk=ordered.task.type_id).update(scoring_scheme='binary')
        result = variants.submit_task_answer(user, work.pk, ordered.pk, is_correct=True,
            task_snapshot={'value': ['3', '4', '8']})
        self.assertEqual(result.task_attempt.score, 1)
