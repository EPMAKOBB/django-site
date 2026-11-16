"""Apply the reviewed final-document delta to a prepared, unpublished catalog."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from apps.recsys.models import (ExamVersion, TaskType, TaskTag, Source, SourceVariant,
    Task, TaskPlacement, TaskSkill, Skill, VariantAttempt)
from .prepare_physics_oge_2027 import type_description, exam_start_info

LEGACY_FINGERPRINT = 'b9614250ee2982e0d43dcbe70a2563ef5fa3508bb6982b9bd38608dc331f71d3'
LEGACY_SOURCE = 'ФИПИ: Физика ОГЭ 2027, проект спецификации, кодификатора и демоверсии из комплекта fi_9_2027'


class Command(BaseCommand):
    help = 'Update the prepared physics draft from final 2027 documents; preview by default.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--expect-database')

    @transaction.atomic
    def handle(self, *args, **options):
        if options['apply'] and options['expect_database'] != connection.settings_dict['NAME']:
            raise CommandError('--apply requires --expect-database matching the selected database.')
        root = Path(settings.BASE_DIR) / 'scripts/data'
        data = json.loads((root / 'physics_oge_2027.json').read_text(encoding='utf-8'))
        task_data = json.loads((root / 'physics_oge_2027_lever_task.json').read_text(encoding='utf-8'))
        fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        exam = ExamVersion.objects.select_for_update().get(slug='phys-oge-2027')
        previous = exam.publication_info.get('physics_oge_preparation')
        if (exam.status != 'draft' or exam.published_at or exam.copied_from_id
                or previous not in {LEGACY_FINGERPRINT, fingerprint}
                or exam.recorded_attempts.exists()
                or VariantAttempt.objects.filter(assignment__template__exam_version=exam).exists()):
            raise CommandError('Only a prepared, unpublished physics draft without issued work can be updated.')
        if exam.task_types.count() != 22:
            raise CommandError('Expected exactly 22 prepared types.')
        if (exam.task_types.filter(display_order__lte=16).exclude(answer_schema__name='test_part_17_chars').exists()
                or exam.task_types.filter(display_order__gte=17).exclude(answer_schema__name='free_form_long').exists()):
            raise CommandError('Run simplify_physics_answer_schemas before updating the documents.')
        source = Source.objects.select_for_update().get(slug='fipi-phys-oge-2027', exam_version=exam)
        if source.description not in {LEGACY_SOURCE, data['source_document']}:
            raise CommandError('Source has author changes; refusing to overwrite.')
        if exam.start_info not in {exam_start_info(approved=False), exam_start_info()}:
            raise CommandError('Exam instructions have author changes; refusing to overwrite.')
        if exam.publication_info.get('source_document') not in {LEGACY_SOURCE, data['source_document']}:
            raise CommandError('Exam source has author changes; refusing to overwrite.')
        quantum = TaskTag.objects.filter(subject=exam.subject, slug__startswith='phys-oge-topic-4-')
        quantum_section = TaskTag.objects.get(subject=exam.subject, slug='phys-oge-section-4')
        quantum_ids = {quantum_section.pk, *quantum.values_list('pk', flat=True)}
        t16 = exam.task_types.get(display_order=16)
        if (t16.tasks.filter(tags__pk__in=quantum_ids).exists()
                or TaskPlacement.objects.filter(task_type=t16, task__tags__pk__in=quantum_ids).exists()):
            raise CommandError('Type 16 has quantum-tagged tasks; review their classification first.')
        for item in data['types']:
            task_type = exam.task_types.select_for_update().get(display_order=item['number'])
            old_item = deepcopy(item)
            if item['number'] == 16:
                old_item['sections'] = [1, 2, 3, 4]
            preserved = exam.publication_info.get('physics_oge_type_overrides', {}).get(str(item['number']), {}).get('description')
            allowed_descriptions = {type_description(old_item, approved=False), type_description(item)}
            if preserved is not None:
                allowed_descriptions.add(preserved)
            if task_type.description not in allowed_descriptions:
                raise CommandError(f'Type {item["number"]}: author description found; refusing to overwrite.')
            task_type.description = preserved if preserved is not None else type_description(item)
            task_type.save(update_fields=['description', 'updated_at'])
        t16.required_tags.remove(quantum_section)
        t16.allowed_tags.remove(*quantum)
        source.description = data['source_document']
        source.save(update_fields=['description', 'updated_at'])
        exam.start_info = exam_start_info()
        exam.publication_info = {**exam.publication_info, 'physics_oge_preparation': fingerprint,
            'source_document': data['source_document'], 'document_status': data['document_status'],
            'document_sha256': data['document_sha256'], 'requirements_checked': False}
        exam.save(update_fields=['start_info', 'publication_info', 'updated_at'])
        t17 = exam.task_types.get(display_order=17)
        if t17.scoring_scheme != 'manual_scaled' or t17.max_score != 3:
            raise CommandError('Type 17 must use manual_scaled, maximum 3.')
        variant = SourceVariant.objects.get(source=source, slug='demo-2027')
        defaults = dict(subject=exam.subject, exam_version=exam, type=t17, source=source,
            source_variant=variant, title=task_data['title'], description=task_data['description'],
            reference_solution=task_data['reference_solution'], assessment_criteria=task_data['assessment_criteria'],
            status='draft', expected_time_seconds=1800, difficulty_level=80,
            default_payload={'source_pages': task_data['source_pages'], 'equipment_set': task_data['equipment_set'],
                             'source_demo_sha256': task_data['source_demo_sha256']})
        task, created = Task.objects.get_or_create(slug=task_data['slug'], defaults=defaults)
        if not created:
            for field, expected in defaults.items():
                if getattr(task, field) != expected:
                    raise CommandError('Existing lever task has author changes; not overwritten.')
        task.full_clean()
        if created:
            tags = list(TaskTag.objects.filter(subject=exam.subject, slug__in=task_data['topic_slugs']))
            if len(tags) != len(task_data['topic_slugs']):
                raise CommandError('Missing task topics.')
            task.tags.set(tags)
            for name in task_data['skills']:
                TaskSkill.objects.create(task=task, skill=Skill.objects.get(subject=exam.subject, name=name))
            TaskPlacement.objects.create(task=task, task_type=t17, status='draft')
        report = {'applied': options['apply'], 'document_status': 'approved',
            'type_16_sections': list(t16.required_tags.values_list('slug', flat=True)),
            'type_16_allowed_topics': t16.allowed_tags.count(), 'lever_task_id': task.pk,
            'lever_task_created': created, 'lever_task_status': task.status,
            'exam_status': exam.status, 'fingerprint': fingerprint}
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        if not options['apply']:
            transaction.set_rollback(True)
