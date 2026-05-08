from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.recsys.models import Task, VariantTemplate
from apps.recsys.service_utils.publication import with_publication_counts


class Command(BaseCommand):
    help = "Report task publication status and public variants blocked by unpublished tasks."

    def handle(self, *args, **options):
        self.stdout.write("Task statuses:")
        status_rows = (
            Task.objects.values("status")
            .annotate(total=Count("id"))
            .order_by("status")
        )
        for row in status_rows:
            self.stdout.write(f"  {row['status'] or '(empty)'}: {row['total']}")

        public_variants = with_publication_counts(
            VariantTemplate.objects.filter(is_public=True, page__is_public=True)
        )
        ready_count = public_variants.filter(unpublished_tasks_count=0).count()
        blocked = public_variants.filter(unpublished_tasks_count__gt=0).order_by(
            "exam_version__name",
            "name",
        )

        self.stdout.write("")
        self.stdout.write(f"Public-ready static variants: {ready_count}")
        self.stdout.write(f"Blocked public static variants: {blocked.count()}")

        for variant in blocked[:50]:
            self.stdout.write(
                f"  #{variant.id} {variant.name}: "
                f"{variant.unpublished_tasks_count} unpublished task(s)"
            )
            tasks = (
                Task.objects.filter(variant_tasks__template=variant)
                .exclude(status=Task.Status.PUBLISHED)
                .values("id", "slug", "title", "status")
                .order_by("id")[:10]
            )
            for task in tasks:
                label = task["slug"] or task["title"]
                self.stdout.write(
                    f"    - #{task['id']} [{task['status']}] {label}"
                )

        if blocked.count() > 50:
            self.stdout.write("  ... output limited to first 50 blocked variants")
