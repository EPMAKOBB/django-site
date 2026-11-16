from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction

from apps.recsys.models import ExamVersion, TaskType


class Command(BaseCommand):
    help = 'Validate manual scoring for free response types in a draft exam; --apply fixes it.'

    def add_arguments(self, parser):
        parser.add_argument('--exam-version-id', type=int, required=True)
        parser.add_argument('--apply', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            exam = ExamVersion.objects.get(pk=options['exam_version_id'])
            if exam.published_at or exam.status != ExamVersion.Status.DRAFT:
                raise CommandError('Only an unpublished draft exam can be changed.')
            changed = 0
            for task_type in exam.task_types.select_related('answer_schema').all():
                config = task_type.answer_schema.config if task_type.answer_schema else {}
                if config.get('manual_check') and task_type.scoring_scheme != TaskType.ScoringScheme.MANUAL_SCALED:
                    self.stdout.write(f'Type {task_type.pk}: {task_type.scoring_scheme} -> manual_scaled')
                    if options['apply']:
                        task_type.scoring_scheme = TaskType.ScoringScheme.MANUAL_SCALED
                        task_type.save(update_fields=['scoring_scheme', 'updated_at'])
                    changed += 1
            self.stdout.write(f'{"Fixed" if options["apply"] else "Needs correction"}: {changed}')
        except ExamVersion.DoesNotExist as exc:
            raise CommandError('Exam not found.') from exc
        except DatabaseError as exc:
            raise CommandError('Database access failed; fixing types requires UPDATE on recsys_tasktype.') from exc
