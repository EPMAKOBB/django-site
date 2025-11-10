"""Utilities for importing pre-generated task datasets."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Iterable, IO

from apps.recsys.models import Task, TaskPreGeneratedDataset


class DatasetImportError(Exception):
    """Raised when the input file cannot be parsed."""


@dataclass(slots=True)
class ImportResult:
    processed_rows: int
    created_datasets: int
    errors: list[str]


def import_pregenerated_datasets(
    *,
    task: Task,
    input_file: IO,
    input_format: str,
    batch_size: int = 200,
) -> ImportResult:
    """Import pre-generated datasets for a task from the given file."""

    parser = _get_parser(input_format)
    processed_rows = 0
    created_count = 0
    errors: list[str] = []
    batch: list[TaskPreGeneratedDataset] = []

    for processed_rows, payload in enumerate(parser(input_file), start=1):
        try:
            dataset = _build_dataset(task, payload)
        except ValueError as exc:
            errors.append(f"Строка {processed_rows}: {exc}")
            continue

        batch.append(dataset)

        if len(batch) >= batch_size:
            TaskPreGeneratedDataset.objects.bulk_create(batch)
            created_count += len(batch)
            batch.clear()

    if batch:
        TaskPreGeneratedDataset.objects.bulk_create(batch)
        created_count += len(batch)

    return ImportResult(
        processed_rows=processed_rows,
        created_datasets=created_count,
        errors=errors,
    )


def _get_parser(input_format: str):
    format_normalized = (input_format or "").lower()
    if format_normalized == "csv":
        return _parse_csv
    if format_normalized == "json":
        return _parse_json
    raise DatasetImportError(f"Неизвестный формат '{input_format}'")


def _parse_csv(file_obj: IO) -> Iterable[dict]:
    stream, should_detach = _as_text_stream(file_obj, newline="")
    try:
        try:
            reader = csv.DictReader(stream)
        except UnicodeDecodeError as exc:  # pragma: no cover - defensive
            raise DatasetImportError(f"Не удалось декодировать CSV: {exc}") from exc

        for row in reader:
            if not any(row.values()):
                continue
            yield {
                "parameter_values": row.get("parameter_values"),
                "correct_answer": row.get("correct_answer"),
                "meta": row.get("meta"),
                "is_active": row.get("is_active"),
            }
    finally:
        if should_detach:
            stream.detach()


def _parse_json(file_obj: IO) -> Iterable[dict]:
    try:
        raw_content = _read_all(file_obj)
    except UnicodeDecodeError as exc:  # pragma: no cover - defensive
        raise DatasetImportError(f"Не удалось декодировать JSON: {exc}") from exc

    if not raw_content.strip():
        return []

    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise DatasetImportError(f"Ошибка разбора JSON: {exc}") from exc

    if not isinstance(data, list):
        raise DatasetImportError("JSON должен содержать список объектов")

    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise DatasetImportError(
                f"Элемент с индексом {index} в JSON не является объектом"
            )
        yield item


def _build_dataset(task: Task, payload: dict) -> TaskPreGeneratedDataset:
    parameter_values = _parse_json_object(
        payload.get("parameter_values"), field_name="parameter_values"
    )
    correct_answer = _parse_json_object(
        payload.get("correct_answer"), field_name="correct_answer"
    )
    meta = _parse_json_object(payload.get("meta"), field_name="meta")
    is_active = _parse_bool(payload.get("is_active"))

    return TaskPreGeneratedDataset(
        task=task,
        parameter_values=parameter_values,
        correct_answer=correct_answer,
        meta=meta,
        is_active=is_active,
    )


def _parse_json_object(value, *, field_name: str) -> dict:
    if value in (None, ""):
        return {}

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return {}
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Поле '{field_name}' должно быть JSON-объектом") from exc

    if isinstance(value, dict):
        return value

    raise ValueError(f"Поле '{field_name}' должно быть JSON-объектом")


def _parse_bool(value) -> bool:
    if value in (None, ""):
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
        raise ValueError("Поле 'is_active' должно быть булевым значением")
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "t", "yes", "y", "да"}:
            return True
        if normalized in {"0", "false", "f", "no", "n", "нет"}:
            return False
    raise ValueError("Поле 'is_active' должно быть булевым значением")


def _as_text_stream(file_obj: IO, newline: str | None = None):
    if hasattr(file_obj, "seek"):
        try:
            file_obj.seek(0)
        except (OSError, io.UnsupportedOperation):  # pragma: no cover - defensive
            pass

    if isinstance(file_obj, io.TextIOBase):
        return file_obj, False

    wrapper = io.TextIOWrapper(file_obj, encoding="utf-8", newline=newline)
    return wrapper, True


def _read_all(file_obj: IO) -> str:
    if hasattr(file_obj, "seek"):
        try:
            file_obj.seek(0)
        except (OSError, io.UnsupportedOperation):  # pragma: no cover - defensive
            pass

    data = file_obj.read()
    if isinstance(data, bytes):
        return data.decode("utf-8")
    return data


__all__ = [
    "DatasetImportError",
    "ImportResult",
    "import_pregenerated_datasets",
]

