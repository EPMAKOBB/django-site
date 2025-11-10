from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from django.core.management.base import BaseCommand, CommandError

from apps.recsys.models import Task, TaskPreGeneratedDataset


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

        parser = self._get_parser(input_format)
        total_rows = 0
        batch: list[TaskPreGeneratedDataset] = []
        parse_errors: list[str] = []
        created_count = 0

        for total_rows, payload in enumerate(parser(path), start=1):
            try:
                dataset = self._build_dataset(task, payload)
            except ValueError as exc:
                parse_errors.append(f"Row {total_rows}: {exc}")
                continue

            batch.append(dataset)

            if len(batch) >= self.batch_size:
                TaskPreGeneratedDataset.objects.bulk_create(batch)
                created_count += len(batch)
                batch.clear()

        if batch:
            TaskPreGeneratedDataset.objects.bulk_create(batch)
            created_count += len(batch)

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {total_rows} row(s); "
                f"created {created_count} dataset(s) for task {task.pk}."
            )
        )

        if parse_errors:
            self.stdout.write(
                self.style.WARNING(
                    f"Encountered {len(parse_errors)} parsing error(s):"
                )
            )
            for error in parse_errors:
                self.stdout.write(f"- {error}")

    def _get_parser(self, input_format: str):
        if input_format == "csv":
            return self._parse_csv
        if input_format == "json":
            return self._parse_json
        raise CommandError(f"Unsupported format '{input_format}'")

    def _parse_csv(self, path: Path) -> Iterable[dict]:
        with path.open("r", encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                if not any(row.values()):
                    continue
                yield {
                    "parameter_values": row.get("parameter_values"),
                    "correct_answer": row.get("correct_answer"),
                    "meta": row.get("meta"),
                    "is_active": row.get("is_active"),
                }

    def _parse_json(self, path: Path) -> Iterable[dict]:
        with path.open("r", encoding="utf-8") as json_file:
            try:
                data = json.load(json_file)
            except json.JSONDecodeError as exc:
                raise CommandError(f"Failed to parse JSON: {exc}") from exc

        if not isinstance(data, list):
            raise CommandError("JSON input must be a list of objects")

        for item in data:
            if not isinstance(item, dict):
                raise CommandError("Each item in JSON input must be an object")
            yield item

    def _build_dataset(self, task: Task, payload: dict) -> TaskPreGeneratedDataset:
        parameter_values = self._parse_json_object(
            payload.get("parameter_values"), field_name="parameter_values"
        )
        correct_answer = self._parse_json_object(
            payload.get("correct_answer"), field_name="correct_answer"
        )
        meta = self._parse_json_object(payload.get("meta"), field_name="meta")
        is_active = self._parse_bool(payload.get("is_active"))

        return TaskPreGeneratedDataset(
            task=task,
            parameter_values=parameter_values,
            correct_answer=correct_answer,
            meta=meta,
            is_active=is_active,
        )

    def _parse_json_object(self, value, field_name: str) -> dict:
        if value in (None, ""):
            return {}

        if isinstance(value, str):
            value = value.strip()
            if not value:
                return {}
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Field '{field_name}' must be a JSON object"
                ) from exc

        if isinstance(value, dict):
            return value

        raise ValueError(f"Field '{field_name}' must be a JSON object")

    def _parse_bool(self, value) -> bool:
        if value in (None, ""):
            return True
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            if value in (0, 1):
                return bool(value)
            raise ValueError("Field 'is_active' must be boolean-like")
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "t", "yes", "y"}:
                return True
            if normalized in {"0", "false", "f", "no", "n"}:
                return False
        raise ValueError("Field 'is_active' must be boolean-like")
