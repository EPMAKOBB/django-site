"""Read-only, repeatable audit before and after an annual-catalog migration."""
import json
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db.models import Count, F, Q
from apps.recsys.models import Attempt, Task, TaskPlacement, ExamVersion, ExamProgressSnapshot, VariantAttempt, VariantTaskAttempt


class Command(BaseCommand):
    help = "Audit annual task bindings and historical context without changing data."

    def add_arguments(self, parser):
        parser.add_argument("--report", help="Write the complete JSON audit to this path.")

    def handle(self, *args, **options):
        conflicts = Task.objects.filter(type__exam_version__isnull=False, exam_version__isnull=False).exclude(exam_version_id=F("type__exam_version_id"))
        duplicate_answers = Attempt.objects.exclude(variant_task_attempt=None).values("variant_task_attempt_id").annotate(n=Count("pk")).filter(n__gt=1)
        result = {
            "counts": {model._meta.model_name: model.objects.count() for model in (Task, Attempt, TaskPlacement, ExamVersion, ExamProgressSnapshot, VariantAttempt, VariantTaskAttempt)},
            "context_origins": dict(Attempt.objects.values_list("context_origin").annotate(n=Count("pk"))),
            "conflicting_task_years": list(conflicts.values_list("pk", flat=True)),
            "tasks_without_annual_type": list(Task.objects.filter(type__exam_version=None).values_list("pk", flat=True)),
            "unknown_attempts": Attempt.objects.filter(Q(context_origin="unknown") | Q(task_type=None)).count(),
            "duplicate_variant_links": duplicate_answers.count(),
            "works_without_snapshot": VariantAttempt.objects.filter(exam_snapshot={}).count(),
        }
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        if options["report"]:
            Path(options["report"]).write_text(rendered + "\n", encoding="utf-8")
        self.stdout.write(rendered)
