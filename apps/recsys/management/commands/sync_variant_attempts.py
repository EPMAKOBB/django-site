from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.recsys.models import Attempt, VariantTaskAttempt
from apps.recsys.service_utils import variants as variant_service


class Command(BaseCommand):
    help = "Create global Attempt rows for checked VariantTaskAttempt rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many variant task attempts are missing Attempt rows without creating them.",
        )

    def handle(self, *args, **options):
        base_queryset = VariantTaskAttempt.objects.filter(
            attempt_number__gt=0,
            task__isnull=False,
            task_snapshot__has_key="response",
        )
        missing_queryset = base_queryset.filter(attempts__isnull=True)
        missing_count = missing_queryset.count()

        if options["dry_run"]:
            self.stdout.write(f"Missing variant Attempts: {missing_count}")
            return

        before_count = Attempt.objects.count()
        variant_service.sync_variant_task_attempts_to_attempts(queryset=missing_queryset)
        created_count = Attempt.objects.count() - before_count
        self.stdout.write(
            self.style.SUCCESS(
                f"Synced variant task attempts (missing={missing_count}, created={created_count})"
            )
        )
