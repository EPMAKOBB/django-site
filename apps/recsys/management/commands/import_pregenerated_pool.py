from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.recsys.models import Task
from apps.recsys.service_utils import pregenerated_import


class Command(BaseCommand):
    help = "Import pre-generated dataset pool for a task"

    batch_size = 200

    def add_arguments(self, parser):
        parser.add_argument("--task-id", type=int, required=True)
        parser.add_argument("--format", choices=("csv", "json"), required=True)
        parser.add_argument("--path", required=True)

    def handle(self, *args, **options):
        task_id = options["task_id"]
        input_format = options["format"]
        path = Path(options["path"]).expanduser()

        try:
            task = Task.objects.get(pk=task_id)
        except Task.DoesNotExist as exc:  # pragma: no cover - defensive
            raise CommandError(f"Task with id={task_id} does not exist") from exc

        if not path.exists():
            raise CommandError(f"File '{path}' does not exist")

        try:
            with path.open("rb") as input_stream:
                result = pregenerated_import.import_pregenerated_datasets(
                    task=task,
                    input_file=input_stream,
                    input_format=input_format,
                    batch_size=self.batch_size,
                )
        except pregenerated_import.DatasetImportError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {result.processed_rows} row(s); "
                f"created {result.created_datasets} dataset(s) for task {task.pk}."
            )
        )

        if result.errors:
            self.stdout.write(
                self.style.WARNING(
                    f"Encountered {len(result.errors)} parsing error(s):"
                )
            )
            for error in result.errors:
                self.stdout.write(f"- {error}")
