from django.core.management.base import BaseCommand
from apps.recsys.service_utils.exam_catalog import invalidate_exam_catalog, get_exam_catalog


class Command(BaseCommand):
    help = "Invalidate and warm reference data after bulk imports (update/bulk_create bypass signals)."

    def handle(self, *args, **options):
        invalidate_exam_catalog()
        catalog = get_exam_catalog()
        self.stdout.write(self.style.SUCCESS(f"Catalog refreshed: {len(catalog['exams'])} exams"))
