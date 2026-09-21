from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from lessons.models import LessonSeries
from lessons.services import generate_series_occurrences


class Command(BaseCommand):
    help = "Заполняет расписание активных серий уроков до настроенного горизонта."

    def handle(self, *args, **options):
        created = 0
        conflicts = 0
        series_count = 0
        errors = 0
        queryset = LessonSeries.objects.filter(status=LessonSeries.Status.ACTIVE).order_by("id")
        for series in queryset.iterator():
            series_count += 1
            try:
                report = generate_series_occurrences(series)
            except ValidationError as exc:
                errors += 1
                self.stderr.write(f"Series {series.id}: {'; '.join(exc.messages)}")
                continue
            created += report.created_count
            conflicts += len(report.conflicts)
            for conflict in report.conflicts:
                self.stderr.write(
                    f"Series {series.id}: {conflict.scheduled_start.isoformat()} — {conflict.message}"
                )
        self.stdout.write(
            f"Серий обработано: {series_count}; уроков создано: {created}; "
            f"конфликтов: {conflicts}; ошибок: {errors}"
        )
        if errors or conflicts:
            raise CommandError("Расписание заполнено частично. Проверьте ошибки и конфликты выше.")
