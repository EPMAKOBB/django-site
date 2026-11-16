"""Prepare an unpublished catalog without changing an existing authored exam."""
import hashlib
import json
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.recsys.models import (ExamVersion, TaskType, AnswerSchema, TaskTag, Skill,
    SkillGroup, SkillGroupItem, ExamBlueprint, ExamBlueprintItem, TaskTypeTransition,
    Source, SourceVariant, VariantAttempt)


def matching(model, lookup, defaults):
    obj, created = model.objects.get_or_create(**lookup, defaults=defaults)
    if not created:
        for field, value in defaults.items():
            if getattr(obj, field) != value:
                raise CommandError(f'{model.__name__} #{obj.pk}: {field} differs; existing author changes were not overwritten.')
    return obj, created


def type_description(item, *, approved=True):
    text = (f"Уровень: {item['level']}. Ориентировочное время: {item['minutes']} мин. "
            f"Разделы кодификатора: {', '.join(map(str, item['sections']))}. "
            + ('По утверждённой спецификации ОГЭ 2027.' if approved else 'По проекту спецификации ОГЭ 2027.'))
    if item['number'] == 17:
        text += ' Эксперимент на реальном оборудовании: комплекты 1, 2, 3, 4, 6. Фото схемы, измерений и вывода.'
    if item['number'] == 18:
        text += ' Текст, рисунки и данные должны быть доступны в условии самостоятельной задачи.'
    return text


def exam_start_info(*, approved=True):
    return ('22 задания, 180 минут, максимум 39 первичных баллов. '
            '№ 1–16 — краткий ответ; № 17–22 — развёрнутое решение с оцениванием по критериям. '
            'Разрешены непрограммируемый калькулятор с тригонометрическими функциями и линейка. '
            'Для № 17 нужно лабораторное оборудование. '
            + ('Материалы 2027 года утверждены.' if approved else 'Материалы 2027 года имеют статус проекта.'))


class Command(BaseCommand):
    help = 'Prepare physics OGE 2027 draft, types, schemas, topics and blueprint. Default: preview with rollback.'

    def add_arguments(self, parser):
        parser.add_argument('--exam-slug', default='phys-oge-2027')
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--expect-database')
        parser.add_argument('--adopt-existing-first-type', action='store_true',
            help='Preserve a sole unused first type and its author labels while preparing the catalog.')

    @transaction.atomic
    def handle(self, *args, **options):
        if options['apply'] and options['expect_database'] != connection.settings_dict['NAME']:
            raise CommandError('--apply requires --expect-database equal to the selected database name.')
        data = json.loads((Path(settings.BASE_DIR) / 'scripts/data/physics_oge_2027.json').read_text(encoding='utf-8'))
        fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        try:
            exam = ExamVersion.objects.select_for_update().select_related('subject').get(slug=options['exam_slug'])
        except (ExamVersion.DoesNotExist, ExamVersion.MultipleObjectsReturned) as exc:
            raise CommandError('Select one existing physics exam by its unique slug.') from exc
        if exam.subject.slug not in {'phys', 'physics'} or exam.year not in (None, 2027):
            raise CommandError('Expected physics, year 2027.')
        if exam.published_at or exam.status == 'archived' or exam.copied_from_id:
            raise CommandError('Only a new, unpublished catalog can be prepared.')
        if exam.recorded_attempts.exists() or VariantAttempt.objects.filter(assignment__template__exam_version=exam).exists():
            raise CommandError('The exam has issued work/history; create another revision instead.')
        previous = exam.publication_info.get('physics_oge_preparation')
        adopted = None
        overrides = exam.publication_info.get('physics_oge_type_overrides', {})
        if exam.task_types.exists() and not previous:
            if not options['adopt_existing_first_type'] or exam.task_types.count() != 1:
                raise CommandError('The exam already has authored types. Refusing to replace its configuration.')
            adopted = exam.task_types.select_for_update().get()
            if adopted.display_order != 1:
                raise CommandError('Only a sole first type can be adopted.')
            for relation in TaskType._meta.related_objects:
                if not relation.many_to_many and relation.related_model.objects.filter(**{relation.field.name: adopted}).exists():
                    raise CommandError('The existing type has related content/history; adoption refused.')
            if adopted.required_tags.exists() or adopted.allowed_tags.exists():
                raise CommandError('The existing first type has author topic settings; review them before adoption.')
            overrides = {'1': {'name': adopted.name, 'slug': adopted.slug, 'description': adopted.description}}
            exam.publication_info = {**exam.publication_info, 'physics_oge_type_overrides': overrides}
        if previous and previous != fingerprint:
            raise CommandError('Preparation manifest changed; review a new revision rather than overwriting existing types.')
        if hasattr(exam, 'score_scale') and exam.score_scale.is_active:
            raise CommandError('An active score scale already exists. Review its source before preparing this draft.')

        schemas = {}
        from apps.recsys.paper_schemas import PAPER_CONFIG, FREE_CONFIG
        configs = {'paper': PAPER_CONFIG, 'written': FREE_CONFIG}
        labels = {'paper': 'test_part_17_chars', 'written': 'free_form_long'}
        for key, config in configs.items():
            schema, _ = matching(AnswerSchema, {'name': labels[key]},
                {'config': config, 'is_active': True})
            schema.full_clean()
            schemas[key] = schema
        for key in ('digits3', 'digits4', 'ordered2', 'choice2', 'choice1', 'number'):
            schemas[key] = schemas['paper']

        section_names = {1: 'Механические явления', 2: 'Тепловые явления',
            3: 'Электромагнитные явления', 4: 'Квантовые явления'}
        broad = {}
        for number, title in section_names.items():
            broad[number], _ = matching(TaskTag, {'subject': exam.subject, 'name': f'ОГЭ · {title}'},
                {'slug': f'phys-oge-section-{number}'})
        topics = {}
        for topic in data['topics']:
            code = topic['code']
            topics[code], _ = matching(TaskTag,
                {'subject': exam.subject, 'name': f"ОГЭ · {code} · {topic['name']}"},
                {'slug': 'phys-oge-topic-' + code.replace('.', '-')})

        blueprint, _ = matching(ExamBlueprint, {'exam_version': exam},
            {'subject': exam.subject, 'title': 'Физика ОГЭ 2027', 'is_active': True, 'time_limit': timedelta(minutes=180)})
        rows = []
        for item in data['types']:
            number = item['number']
            section = 'Понятийный аппарат' if number <= 14 else 'Методологические умения' if number <= 17 else 'Работа с текстом' if number == 18 else 'Решение задач'
            description = type_description(item)
            task_type, created = matching(TaskType, {'exam_version': exam, 'display_order': number},
                self.type_defaults(exam, item, description, schemas, overrides, adopted))
            task_type.full_clean()
            required = {broad[n].pk for n in item['sections']}
            allowed = {tag.pk for code, tag in topics.items() if int(code.split('.')[0]) in item['sections']}
            for field, expected in [('required_tags', required), ('allowed_tags', allowed)]:
                manager = getattr(task_type, field)
                if not created and task_type != adopted and set(manager.values_list('pk', flat=True)) != expected:
                    raise CommandError(f'Type {number}: {field} changed; refusing to overwrite.')
                if created or task_type == adopted:
                    manager.set(expected)
            matching(ExamBlueprintItem, {'blueprint': blueprint, 'order': number},
                {'task_type': task_type, 'count': 1, 'section': section, 'score_override': None})
            transition, _ = matching(TaskTypeTransition,
                {'target_exam': exam, 'target_type': task_type, 'source_type': None},
                {'relation': 'added', 'approved': True, 'notes': 'Новый тип по проекту документов ФИПИ 2027, без переноса старого банка.'})
            transition.full_clean()
            rows.append({'number': number, 'type_id': task_type.pk, 'rule': task_type.scoring_scheme, 'max_score': task_type.max_score})
        if exam.task_types.count() != 22 or blueprint.items.count() != 22:
            raise CommandError('Unexpected extra types/blueprint positions. Existing content was not changed.')

        group, _ = SkillGroup.objects.get_or_create(exam_version=exam, title='Физика ОГЭ: проверяемые умения')
        for order, title in enumerate(data['skills'], 1):
            skill, _ = Skill.objects.get_or_create(subject=exam.subject, name=title)
            matching(SkillGroupItem, {'group': group, 'skill': skill}, {'label': title, 'order': order})
        source, _ = matching(Source, {'slug': 'fipi-phys-oge-2027'},
            {'name': 'ФИПИ — Физика ОГЭ 2027', 'exam_version': exam, 'description': data['source_document']})
        variant, _ = matching(SourceVariant, {'source': source, 'label': 'Демоверсия 2027'}, {'slug': 'demo-2027'})
        exam.exam_kind, exam.year, exam.status, exam.is_default = 'oge', 2027, 'draft', False
        exam.start_info = exam_start_info()
        exam.publication_info = {**exam.publication_info, 'physics_oge_preparation': fingerprint,
            'source_document': data['source_document'], 'requirements_checked': False, 'scale_checked': True,
            'document_status': data['document_status'], 'document_sha256': data['document_sha256']}
        exam.save()
        report = {'applied': options['apply'], 'exam_slug': exam.slug, 'status': exam.status,
            'types': rows, 'max_primary': sum(i['max_score'] for i in data['types']),
            'time_minutes': 180, 'topics': len(topics), 'source_variant_id': variant.pk,
            'tasks': exam.tasks.count(), 'scale': 'disabled; official boundaries not supplied',
            'next': 'Fill the bank and task-specific criteria, review requirements, then use the publication workflow.'}
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        if not options['apply']:
            transaction.set_rollback(True)

    def type_defaults(self, exam, item, description, schemas, overrides, adopted):
        number = item['number']
        defaults = {'subject': exam.subject, 'name': f"{number}. {item['title']}", 'slug': str(number),
                    'description': description, 'answer_schema': schemas[item['schema']],
                    'scoring_scheme': item['scoring_scheme'], 'max_score': item['max_score']}
        preserved = overrides.get(str(number), {})
        for field in ('name', 'slug', 'description'):
            if field in preserved:
                defaults[field] = preserved[field]
        if adopted is not None and number == 1:
            for field, value in defaults.items():
                setattr(adopted, field, value)
            adopted.save()
        return defaults
