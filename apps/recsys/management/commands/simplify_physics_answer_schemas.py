"""Retire only unused, unmodified schemas from the prepared physics draft."""
import json
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from apps.recsys.models import AnswerSchema, ExamVersion, VariantAttempt
from apps.recsys.paper_schemas import PAPER_CONFIG, FREE_CONFIG, LEGACY_PHYSICS_SCHEMAS
from .prepare_physics_oge_2027 import matching


class Command(BaseCommand):
    help = 'Use shared paper/free forms for an unused physics draft; default is preview.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--expect-database')

    @transaction.atomic
    def handle(self, *args, **options):
        if options['apply'] and options['expect_database'] != connection.settings_dict['NAME']:
            raise CommandError('--apply requires --expect-database matching the selected database.')
        exam = ExamVersion.objects.select_for_update().get(slug='phys-oge-2027')
        if (exam.status != 'draft' or exam.published_at or not exam.publication_info.get('physics_oge_preparation')
                or exam.tasks.exists() or exam.recorded_attempts.exists()
                or VariantAttempt.objects.filter(assignment__template__exam_version=exam).exists()):
            raise CommandError('Only an unused, prepared physics draft can be simplified.')
        paper, _ = matching(AnswerSchema, {'name': 'test_part_17_chars'}, {'config': PAPER_CONFIG, 'is_active': True})
        free, _ = matching(AnswerSchema, {'name': 'free_form_long'}, {'config': FREE_CONFIG, 'is_active': True})
        deleted, retained = [], []
        for label, config in LEGACY_PHYSICS_SCHEMAS.items():
            schema = AnswerSchema.objects.select_for_update().filter(name=f'Физика ОГЭ 2027: {label}').first()
            if not schema:
                continue
            if schema.config != {'rows': 1, **config}:
                raise CommandError(f'{schema.name}: author changes found; refusing to change it.')
            replacement = free if label == 'Развёрнутый ответ' else paper
            for task_type in exam.task_types.filter(answer_schema=schema):
                if (task_type.scoring_scheme == 'manual_scaled') != (replacement == free):
                    raise CommandError('Unexpected scoring/schema combination.')
                task_type.answer_schema = replacement
                task_type.save(update_fields=['answer_schema', 'updated_at'])
            # Never let SET_NULL silently erase a reference in another subject.
            referenced = any(getattr(schema, rel.get_accessor_name()).exists()
                             for rel in AnswerSchema._meta.related_objects)
            if referenced:
                retained.append(schema.name)
            else:
                deleted.append(schema.name)
                schema.delete()
        report = {'applied': options['apply'], 'deleted': deleted, 'retained_as_used_elsewhere': retained,
                  'paper_types': exam.task_types.filter(answer_schema=paper).count(),
                  'written_types': exam.task_types.filter(answer_schema=free).count()}
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        if not options['apply']:
            transaction.set_rollback(True)
