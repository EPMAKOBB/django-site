from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Sequence

from django import forms
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
import re

from subjects.models import Subject
from .models import ExamVersion, Task, TaskAttachment, TaskType, Source, SourceVariant


@dataclass(frozen=True)
class AnswerSegment:
    kind: str  # "dict" or "list"
    key: Any


@dataclass
class AnswerFieldMetadata:
    name: str
    label: str
    segments: tuple[AnswerSegment, ...]
    value_type: str
    widget: str
    input_type: str | None = None
    step: str | None = None
    choices: tuple[tuple[str, str], ...] = ()


def _detect_value_type(sample: Any) -> str:
    if isinstance(sample, bool):
        return "boolean"
    if isinstance(sample, int):
        return "integer"
    if isinstance(sample, float):
        return "float"
    return "string"


def _format_answer_label(segments: tuple[AnswerSegment, ...]) -> str:
    parts: list[str] = [str(_("Ответ"))]
    for index, segment in enumerate(segments):
        if segment.kind == "dict":
            key_display = str(segment.key)
            if index == 0 and key_display == "value":
                continue
            parts.append(key_display)
        else:
            element_index = int(segment.key) + 1
            parts.append(str(_("Элемент %(index)s") % {"index": element_index}))
    if not parts:
        return str(_("Ответ"))
    return " → ".join(parts)


def _build_field_name(segments: tuple[AnswerSegment, ...]) -> str:
    if not segments:
        return "answer__value"
    tokens = [str(segment.key) for segment in segments]
    return "answer__" + "__".join(tokens)


def build_answer_fields(correct_answer: Any) -> list[AnswerFieldMetadata]:
    fields: list[AnswerFieldMetadata] = []

    def _make_field(
        sample_value: Any, segments: tuple[AnswerSegment, ...]
    ) -> AnswerFieldMetadata:
        value_type = _detect_value_type(sample_value)
        name = _build_field_name(segments) if segments else "answer__value"
        label = _format_answer_label(segments) if segments else _("Ответ")
        widget = "input"
        input_type: str | None = "text"
        step: str | None = None
        choices: tuple[tuple[str, str], ...] = ()

        if value_type == "boolean":
            widget = "select"
            input_type = None
            choices = (("true", _("Да")), ("false", _("Нет")))
        elif value_type == "integer":
            input_type = "number"
        elif value_type == "float":
            input_type = "number"
            step = "any"

        return AnswerFieldMetadata(
            name=name,
            label=label,
            segments=segments,
            value_type=value_type,
            widget=widget,
            input_type=input_type,
            step=step,
            choices=choices,
        )

    def _walk(node: Any, segments: tuple[AnswerSegment, ...]) -> None:
        if isinstance(node, dict):
            if not node:
                return
            for key, value in node.items():
                _walk(value, segments + (AnswerSegment(kind="dict", key=key),))
        elif isinstance(node, list):
            if not node:
                return
            for index, value in enumerate(node):
                _walk(value, segments + (AnswerSegment(kind="list", key=index),))
        else:
            fields.append(_make_field(node, segments))

    if isinstance(correct_answer, (dict, list)):
        _walk(correct_answer, tuple())
    else:
        if correct_answer is not None:
            fields.append(_make_field(correct_answer, tuple()))

    return fields


def convert_answer_value(field: AnswerFieldMetadata, raw_value: str) -> Any:
    value = (raw_value or "").strip()
    if not value:
        raise ValueError(_("Заполните поле «%(label)s».") % {"label": field.label})

    if field.value_type == "integer":
        try:
            return int(value)
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError(
                _("Поле «%(label)s» должно быть целым числом.") % {"label": field.label}
            ) from exc
    if field.value_type == "float":
        normalised = value.replace(",", ".")
        try:
            return float(normalised)
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError(
                _("Поле «%(label)s» должно быть числом.") % {"label": field.label}
            ) from exc
    if field.value_type == "boolean":
        lowered = value.lower()
        truthy = {"true", "1", "yes", "y", "on", "да", "истина"}
        falsy = {"false", "0", "no", "n", "off", "нет", "ложь"}
        if lowered in truthy:
            return True
        if lowered in falsy:
            return False
        raise ValueError(
            _("Невозможно распознать значение для «%(label)s».")
            % {"label": field.label}
        )

    return value


def _initial_structure(template: Any) -> Any:
    if isinstance(template, dict):
        return {}
    if isinstance(template, list):
        return []
    return None


def _insert_value(
    target: Any, segments: tuple[AnswerSegment, ...], value: Any
) -> None:
    current = target
    for index, segment in enumerate(segments):
        is_last = index == len(segments) - 1
        if segment.kind == "dict":
            key = segment.key
            if is_last:
                current[key] = value
            else:
                next_segment = segments[index + 1]
                if key not in current or current[key] is None:
                    current[key] = _initial_structure(
                        [] if next_segment.kind == "list" else {}
                    )
                current = current[key]
        else:
            key_index = int(segment.key)
            while len(current) <= key_index:
                current.append(None)
            if is_last:
                current[key_index] = value
            else:
                next_segment = segments[index + 1]
                if current[key_index] is None:
                    current[key_index] = _initial_structure(
                        [] if next_segment.kind == "list" else {}
                    )
                current = current[key_index]


def assemble_answer_structure(
    template: Any, fields: Sequence[AnswerFieldMetadata], converted: dict[str, Any]
) -> Any:
    base = _initial_structure(template)
    if base is None:
        field = fields[0] if fields else None
        return converted.get(field.name) if field else None

    for field in fields:
        _insert_value(base, field.segments, converted[field.name])
    return base


def compare_answers(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or expected.keys() != actual.keys():
            return False
        return all(compare_answers(expected[key], actual[key]) for key in expected)
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return False
        return all(compare_answers(exp, act) for exp, act in zip(expected, actual))
    if isinstance(expected, str):
        return expected.strip().casefold() == str(actual).strip().casefold()
    if isinstance(expected, float):
        try:
            actual_value = float(actual)
        except (TypeError, ValueError):
            return False
        return abs(expected - actual_value) <= 1e-9
    return expected == actual


class TaskAnswerForm(forms.Form):
    """
    Dynamic form that mirrors the structure of a task's correct answer.
    Provides rendering metadata and builds a cleaned answer structure
    for downstream processing.
    """

    def __init__(
        self,
        correct_answer: Any,
        *args,
        initial_answer: Any | None = None,
        **kwargs,
    ) -> None:
        self.correct_answer_template = correct_answer
        self.answer_fields = build_answer_fields(correct_answer)
        initial_values = self._build_initial_values(initial_answer)
        if initial_values:
            merged_initial = {}
            if kwargs.get("initial"):
                merged_initial.update(kwargs["initial"])
            merged_initial.update(initial_values)
            kwargs["initial"] = merged_initial
        super().__init__(*args, **kwargs)
        for meta in self.answer_fields:
            field = self._build_form_field(meta)
            if not self.is_bound and meta.name in self.initial:
                field.initial = self.initial[meta.name]
            self.fields[meta.name] = field
        self.converted_values: dict[str, Any] = {}
        self.answer: Any | None = None

    def _build_form_field(self, meta: AnswerFieldMetadata) -> forms.Field:
        field_id = f"{meta.name}-input"
        if meta.widget == "select":
            choices = [("", _("Выберите значение"))] + list(meta.choices)
            return forms.ChoiceField(
                label=meta.label,
                choices=choices,
                required=True,
                widget=forms.Select(attrs={"id": field_id, "class": "module-detail__answer-input"}),
            )

        attrs: dict[str, Any] = {"id": field_id, "class": "module-detail__answer-input", "placeholder": str(meta.label)}
        if meta.input_type == "number":
            attrs["step"] = meta.step or "1"
            if meta.value_type == "float":
                attrs["inputmode"] = "decimal"
            widget: forms.Widget = forms.NumberInput(attrs=attrs)
        else:
            widget = forms.TextInput(attrs=attrs)
        return forms.CharField(label=meta.label, required=True, widget=widget)

    def _build_initial_values(self, answer: Any | None) -> dict[str, Any]:
        if answer is None or not self.answer_fields:
            return {}

        def _pluck(node: Any, segments: tuple[AnswerSegment, ...]):
            current = node
            if not segments:
                return current
            for segment in segments:
                if segment.kind == "dict":
                    if not isinstance(current, Mapping) or segment.key not in current:
                        return None
                    current = current[segment.key]
                else:
                    if not isinstance(current, (list, tuple)):
                        return None
                    index = int(segment.key)
                    if index < 0 or index >= len(current):
                        return None
                    current = current[index]
            return current

        initial: dict[str, Any] = {}
        for meta in self.answer_fields:
            value = _pluck(answer, meta.segments)
            if value is None:
                continue
            if meta.value_type == "boolean":
                initial[meta.name] = "true" if value is True else "false"
            else:
                initial[meta.name] = value
        return initial

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        converted: dict[str, Any] = {}
        for meta in self.answer_fields:
            raw_value = cleaned.get(meta.name, "")
            raw_text = "" if raw_value in (None, "") else str(raw_value)
            try:
                converted[meta.name] = convert_answer_value(meta, raw_text)
            except ValueError as exc:
                self.add_error(meta.name, str(exc))

        if self.errors:
            return cleaned

        self.converted_values = converted
        self.answer = assemble_answer_structure(
            self.correct_answer_template, self.answer_fields, converted
        )
        return cleaned

    @property
    def is_available(self) -> bool:
        return bool(self.answer_fields)

    def get_answer(self) -> Any:
        return self.answer


class TaskUploadForm(forms.ModelForm):
    """
    Simplified form for creating a task with optional image and up to two files.
    """

    image = forms.FileField(required=False, help_text="SVG/PNG/JPEG и др.")
    file_a = forms.FileField(required=False, help_text="Основной файл (или A для задачи 27)")
    file_b = forms.FileField(required=False, help_text="Дополнительный файл (B для задачи 27)")

    class Meta:
        model = Task
        fields = [
            "subject",
            "exam_version",
            "type",
            "source",
            "source_variant",
            "slug",
            "title",
            "description",
            "rendering_strategy",
            "difficulty_level",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
        }

    def clean_slug(self):
        value = self.cleaned_data.get("slug") or self.cleaned_data.get("title")
        value = slugify(value or "")
        if not value:
            raise forms.ValidationError("Slug обязателен.")
        return value

    def clean(self):
        cleaned = super().clean()
        subject: Subject | None = cleaned.get("subject")
        exam: ExamVersion | None = cleaned.get("exam_version")
        task_type: TaskType | None = cleaned.get("type")
        source: Source | None = cleaned.get("source")
        source_variant: SourceVariant | None = cleaned.get("source_variant")

        if exam and subject and exam.subject_id != subject.id:
            self.add_error("exam_version", "Версия экзамена должна совпадать с предметом.")
        if task_type and subject and task_type.subject_id != subject.id:
            self.add_error("type", "Тип задачи должен совпадать с предметом.")
        if source_variant:
            if source and source_variant.source_id != source.id:
                self.add_error("source_variant", "Вариант источника должен соответствовать источнику.")
            if not source:
                cleaned["source"] = source_variant.source
        return cleaned

    def create_task_with_attachments(self) -> Task:
        """
        Save task and attachments based on uploaded files.
        """
        task: Task = self.save(commit=False)
        task.is_dynamic = False
        task.save()
        self.save_m2m()

        files_to_create: list[TaskAttachment] = []
        upload_map = [
            ("A", self.files.get("file_a")),
            ("B", self.files.get("file_b")),
        ]
        for order, (label, uploaded) in enumerate(upload_map, start=1):
            if not uploaded:
                continue
            files_to_create.append(
                TaskAttachment(
                    task=task,
                    kind=TaskAttachment.Kind.FILE,
                    file=uploaded,
                    label=label,
                    order=order,
                )
            )

        # Image as attachment (allows SVG and other formats)
        image_file = self.files.get("image")
        if image_file:
            files_to_create.append(
                TaskAttachment(
                    task=task,
                    kind=TaskAttachment.Kind.IMAGE,
                    file=image_file,
                    label="img",
                    order=0,
                )
            )

        for att in files_to_create:
            att.save()

        # Replace tokens ![[att:<id_or_label>]] in description with real URLs
        if task.description:
            # Use all attachments of the task (existing + new)
            attachments = list(task.attachments.all())
            by_id = {a.id: a for a in attachments if a.id}
            by_label = { (a.label or "").lower(): a for a in attachments if a.label }
            pattern = re.compile(r"!\[\[att:([A-Za-z0-9_-]+)\]\]", re.IGNORECASE)

            def _replace(match: re.Match[str]) -> str:
                token = match.group(1)
                att = None
                if token.isdigit():
                    att = by_id.get(int(token))
                if not att:
                    att = by_label.get(token.lower())
                if not att:
                    return match.group(0)
                url = att.file.url
                label = att.label or f"att{att.id}"
                if att.kind == TaskAttachment.Kind.IMAGE:
                    return f"![{label}]({url})"
                return f"[{label}]({url})"

            new_desc = pattern.sub(_replace, task.description)
            if new_desc != task.description:
                task.description = new_desc
                task.save(update_fields=["description"])

        return task
