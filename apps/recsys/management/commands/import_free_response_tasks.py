import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.recsys.models import SourceVariant, Task, TaskPlacement, TaskType


class Command(BaseCommand):
    help = "Validate or import tasks with a text reference answer and manual scoring."

    def add_arguments(self, parser):
        parser.add_argument('--path', required=True)
        parser.add_argument('--exam-version-id', type=int, required=True)
        parser.add_argument('--source-variant-id', type=int, required=True)
        parser.add_argument('--apply', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            entries = json.loads(Path(options['path']).read_text(encoding='utf-8-sig'))
            variant = SourceVariant.objects.select_related('source__exam_version').get(pk=options['source_variant_id'])
            exam = variant.source.exam_version
            if not exam or exam.pk != options['exam_version_id']:
                raise CommandError('Source variant must belong to the requested exam.')
            if not isinstance(entries, list) or not entries:
                raise CommandError('Expected a nonempty JSON list.')
            tasks = []
            seen = set()
            for entry in entries:
                if not isinstance(entry, dict):
                    raise CommandError('Each task must be a JSON object.')
                for field in ('title', 'slug', 'description', 'correct_answer'):
                    if not isinstance(entry.get(field), str) or not entry[field].strip():
                        raise CommandError(f'{field} must be nonempty text; answer grids are not accepted.')
                task_type = TaskType.objects.select_related('answer_schema').get(exam_version=exam, display_order=entry['type_number'])
                schema = task_type.answer_schema
                config = schema.config if schema else {}
                if not schema or not schema.is_active or not config.get('manual_check') or config.get('ui_hint') != 'textarea' or (config.get('rows', 1), config.get('cols', 1)) != (1, 1):
                    raise CommandError('Task type must have an active 1x1 free response schema.')
                task = Task(subject_id=exam.subject_id, exam_version=exam, type=task_type,
                            source=variant.source, source_variant=variant,
                            title=entry['title'], slug=entry['slug'], description=entry['description'],
                            correct_answer=entry['correct_answer'], rendering_strategy=Task.RenderingStrategy.MARKDOWN,
                            status=Task.Status.DRAFT, answer_schema=schema,
                            reference_solution=entry.get('reference_solution', ''),
                            assessment_criteria=entry.get('assessment_criteria', ''),
                            scoring_scheme=TaskType.ScoringScheme.MANUAL_SCALED, max_score=task_type.max_score)
                task.full_clean()
                key = (task.type_id, task.title)
                if task.slug in seen or key in seen:
                    raise CommandError('Duplicate slug or title within the input.')
                seen.update((task.slug, key))
                tasks.append(task)
            for task in tasks:
                if options['apply']:
                    task.save(force_insert=True)
                    TaskPlacement(task=task, task_type=task.type,
                                  status=TaskPlacement.Status.ACTIVE,
                                  scoring_scheme=TaskType.ScoringScheme.MANUAL_SCALED,
                                  answer_schema=task.answer_schema, max_score=task.max_score).save(force_insert=True)
                self.stdout.write(f'{task.slug}: {task.max_score} points, manual_scaled, draft')
            self.stdout.write(f'{"Imported" if options["apply"] else "Validated (no writes)"}: {len(tasks)}')
        except (OSError, ValueError, KeyError, TypeError, ValidationError, SourceVariant.DoesNotExist, TaskType.DoesNotExist, TaskType.MultipleObjectsReturned) as exc:
            raise CommandError(str(exc)) from exc
