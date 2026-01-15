from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Sequence
from pathlib import Path

from django import forms
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
import re
import json

from subjects.models import Subject
from .models import (
    ExamVersion,
    AnswerSchema,
    Skill,
    Task,
    TaskAttachment,
    TaskSkill,
    TaskTag,
    TaskType,
    Source,
    SourceVariant,
)


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
    required: bool = True
    blank_value: Any = None


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
        required = not (sample_value is None or (isinstance(sample_value, str) and sample_value == ""))
        blank_value: Any = "" if isinstance(sample_value, str) and sample_value == "" else None

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
            required=required,
            blank_value=blank_value,
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
        if not field.required:
            return field.blank_value
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
                required=meta.required,
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
        return forms.CharField(label=meta.label, required=meta.required, widget=widget)

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
    Simplified form for creating a task with optional image and attachments.
    """

    class MultiFileInput(forms.ClearableFileInput):
        allow_multiple_selected = True

    class MultiFileField(forms.FileField):
        def to_python(self, data):
            if not data:
                return []
            if isinstance(data, (list, tuple)):
                return [forms.FileField.to_python(self, item) for item in data if item]
            return [forms.FileField.to_python(self, data)]

        def clean(self, data, initial=None):
            files = self.to_python(data)
            if self.required and not files:
                raise forms.ValidationError(self.error_messages["required"], code="required")
            return files

    answer_inputs = forms.CharField(required=False, widget=forms.HiddenInput())
    correct_answer = forms.JSONField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": '{"value": 42}'}),
        help_text="JSON со структурой правильного ответа.",
    )
    tags = forms.ModelMultipleChoiceField(
        queryset=TaskTag.objects.none(),
        required=False,
        help_text="Только обязательные теги выбранного типа.",
        widget=forms.SelectMultiple(attrs={"size": 5}),
    )
    skills = forms.ModelMultipleChoiceField(
        queryset=Skill.objects.none(),
        required=False,
        help_text="Навыки предмета. Вес по умолчанию = 1.0.",
        widget=forms.SelectMultiple(attrs={"size": 6}),
    )
    image = forms.FileField(required=False, help_text="SVG/PNG/JPEG и др.")
    attachments = MultiFileField(
        required=False,
        widget=MultiFileInput(attrs={"multiple": True}),
        help_text="Основной файл (или несколько).",
    )

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
            "correct_answer",
            "tags",
            "rendering_strategy",
            "difficulty_level",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._task_type: TaskType | None = None
        # When bound, try to resolve task type early for validation hooks
        type_id = None
        if "data" in kwargs:
            data = kwargs["data"]
        else:
            data = self.data
        try:
            type_id = int(data.get("type")) if data else None
        except (TypeError, ValueError):
            type_id = None
        if type_id:
            self._task_type = TaskType.objects.select_related("answer_schema").filter(id=type_id).first()

        source_id = None
        try:
            source_id = int(data.get("source")) if data else None
        except (TypeError, ValueError):
            source_id = None
        if not source_id:
            initial_source = self.initial.get("source")
            if initial_source:
                try:
                    source_id = int(initial_source)
                except (TypeError, ValueError):
                    source_id = None
        if not source_id and self.instance and self.instance.source_id:
            source_id = self.instance.source_id

        if "source_variant" in self.fields:
            variants_qs = SourceVariant.objects.select_related("source").order_by("source__name", "label")
            if source_id:
                variants_qs = variants_qs.filter(source_id=source_id)
            self.fields["source_variant"].queryset = variants_qs

        if "tags" in self.fields:
            self.fields["tags"].queryset = TaskTag.objects.select_related("subject").order_by(
                "subject__name", "name"
            )
        if "skills" in self.fields:
            self.fields["skills"].queryset = Skill.objects.select_related("subject").order_by(
                "subject__name", "name"
            )

    def clean_slug(self):
        value = self.cleaned_data.get("slug") or self.cleaned_data.get("title")
        value = slugify(value or "")
        if not value:
            raise forms.ValidationError("Slug обязателен.")
        return value

    def clean_correct_answer(self):
        raw_from_inputs = self.cleaned_data.get("answer_inputs")
        parsed_from_inputs = None
        if raw_from_inputs:
            try:
                parsed_from_inputs = json.loads(raw_from_inputs)
            except json.JSONDecodeError as exc:
                raise forms.ValidationError("Невозможно распарсить ответ из формы ввода.") from exc

        value = parsed_from_inputs if parsed_from_inputs is not None else self.cleaned_data.get("correct_answer")
        if value in (None, "", {}):
            return {}
        has_schema = bool(self._task_type and self._task_type.answer_schema_id)
        if not has_schema and not isinstance(value, dict):
            value = {"value": value}
        return value

    def _coerce_cell(self, input_type: str, value: Any, *, label: str, max_length: int | None = None) -> Any:
        if value is None or value == "":
            raise forms.ValidationError(f"Заполните поле «{label}».")
        if input_type == "uint":
            try:
                ivalue = int(value)
            except (TypeError, ValueError):
                raise forms.ValidationError(f"Поле «{label}» должно быть целым числом.")
            if ivalue < 0:
                raise forms.ValidationError(f"Поле «{label}» должно быть неотрицательным.")
            return ivalue
        if input_type == "int":
            try:
                return int(value)
            except (TypeError, ValueError):
                raise forms.ValidationError(f"Поле «{label}» должно быть целым числом.")
        if input_type == "float":
            try:
                return float(value)
            except (TypeError, ValueError):
                raise forms.ValidationError(f"Поле «{label}» должно быть числом.")
        # string / text / char fallback
        text = "" if value is None else str(value)
        if input_type == "char":
            max_length = max_length or 1
        if max_length is not None and len(text) > max_length:
            raise forms.ValidationError(f"Поле «{label}» должно содержать не более {max_length} символа.")
        return text

    def _normalize_answer_by_schema(self, schema: AnswerSchema, value: Any) -> Any:
        cfg = schema.config or {}
        rows = int(cfg.get("rows") or 1)
        cols = int(cfg.get("cols") or 1)
        input_type = cfg.get("input_type") or "string"
        allow_blank_rows = bool(cfg.get("allow_blank_rows"))
        allow_blank_cells = bool(cfg.get("allow_blank_cells"))
        per_cell_max_length = cfg.get("per_cell_max_length")
        if per_cell_max_length:
            input_type = "char"
            try:
                per_cell_max_length = int(per_cell_max_length)
            except (TypeError, ValueError):
                per_cell_max_length = 1

        def coerce_cell(val: Any, *, row: int, col: int) -> Any:
            if allow_blank_cells and val in ("", None):
                if input_type in ("uint", "int", "float"):
                    return None
                return ""
            label = f"({row + 1}, {col + 1})"
            return self._coerce_cell(input_type, val, label=label, max_length=per_cell_max_length)

        # 1x1 scalar
        if rows == 1 and cols == 1:
            if isinstance(value, dict) and "value" in value:
                value = value.get("value")
            if isinstance(value, list) and len(value) == 1:
                value = value[0]
            return coerce_cell(value, row=0, col=0)

        # Single row, multiple columns -> flat list
        if rows == 1:
            if not isinstance(value, (list, tuple)):
                raise forms.ValidationError("Ответ должен содержать список из %d элементов." % cols)
            if len(value) != cols:
                raise forms.ValidationError("Ответ должен содержать ровно %d элементов." % cols)
            return [coerce_cell(v, row=0, col=idx) for idx, v in enumerate(value)]

        # Multiple rows -> list of rows
        if not isinstance(value, (list, tuple)):
            raise forms.ValidationError("Ответ должен содержать список строк длиной %d." % rows)

        normalized_rows: list[list[Any]] = []
        for r in range(rows):
            row_val = value[r] if r < len(value) else []
            if row_val in ("", None):
                row_val = []
            if not isinstance(row_val, (list, tuple)):
                raise forms.ValidationError(f"Строка {r+1} должна быть списком из {cols} элементов.")
            if not allow_blank_rows and len(row_val) != cols:
                raise forms.ValidationError(f"Строка {r+1} должна содержать ровно {cols} элементов.")

            row_items: list[Any] = []
            for c in range(cols):
                if c < len(row_val):
                    cell_val = row_val[c]
                else:
                    cell_val = None
                if allow_blank_rows and (cell_val in ("", None)):
                    row_items.append(None)
                    continue
                row_items.append(coerce_cell(cell_val, row=r, col=c))
            normalized_rows.append(row_items)

        if allow_blank_rows:
            # Remove trailing rows that are fully empty
            while normalized_rows and all(v is None for v in normalized_rows[-1]):
                normalized_rows.pop()
        return normalized_rows

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
        if task_type and "tags" in cleaned:
            required_ids = set(task_type.required_tags.values_list("id", flat=True))
            selected_ids = (
                set(cleaned.get("tags").values_list("id", flat=True))
                if cleaned.get("tags")
                else set()
            )
            extra = selected_ids - required_ids
            if extra:
                self.add_error("tags", "Можно выбрать только обязательные теги выбранного типа.")
        if subject and cleaned.get("skills"):
            bad_skills = [s for s in cleaned["skills"] if s.subject_id != subject.id]
            if bad_skills:
                self.add_error("skills", "Все выбранные навыки должны относиться к предмету задания.")
        if source_variant:
            if source and source_variant.source_id != source.id:
                self.add_error("source_variant", "Вариант источника должен соответствовать источнику.")
            if not source:
                cleaned["source"] = source_variant.source

        answer_value = cleaned.get("correct_answer")
        if task_type and task_type.answer_schema and answer_value not in (None, {}):
            try:
                normalized_answer = self._normalize_answer_by_schema(task_type.answer_schema, answer_value)
            except forms.ValidationError as exc:
                self.add_error("correct_answer", exc)
            else:
                cleaned["correct_answer"] = normalized_answer
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
        uploaded_files = list(self.files.getlist("attachments")) if hasattr(self.files, "getlist") else []
        provided_names = list(self.data.getlist("attachment_names")) if hasattr(self, "data") else []

        for index, uploaded in enumerate(uploaded_files, start=1):
            if not uploaded:
                continue

            provided_name = (provided_names[index - 1] if index - 1 < len(provided_names) else "").strip()
            download_name = provided_name or uploaded.name
            base_label_source = provided_name or uploaded.name
            label_slug = slugify(Path(base_label_source).stem) or f"file{index}"

            files_to_create.append(
                TaskAttachment(
                    task=task,
                    kind=TaskAttachment.Kind.FILE,
                    file=uploaded,
                    label=label_slug[:50],
                    download_name_override=download_name[:255] if download_name else "",
                    order=index,
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

        # Attach selected skills with default weight
        skills = list(self.cleaned_data.get("skills") or [])
        for skill in skills:
            TaskSkill.objects.get_or_create(task=task, skill=skill, defaults={"weight": 1.0})

        # Replace tokens ![[att:<id_or_label>]] in description with real URLs
        if task.description:
            # Use all attachments of the task (existing + new)
            attachments = list(task.attachments.all())
            by_id = {a.id: a for a in attachments if a.id}

            def _token_keys(att: TaskAttachment) -> set[str]:
                keys: set[str] = set()
                label = (att.label or "").lower()
                if label:
                    slug_label = slugify(label)
                    keys.add(label)
                    keys.add(slug_label)
                    keys.add(slug_label.replace("-", ""))
                file_name = Path(att.file.name).name
                stem = Path(file_name).stem.lower()
                if stem:
                    slug_stem = slugify(stem)
                    keys.add(slug_stem)
                    keys.add(slug_stem.replace("-", ""))
                if att.download_name_override:
                    dn_stem = Path(att.download_name_override).stem.lower()
                    slug_dn = slugify(dn_stem)
                    keys.add(slug_dn)
                    keys.add(slug_dn.replace("-", ""))
                return {k for k in keys if k}

            by_token: dict[str, TaskAttachment] = {}
            for att in attachments:
                for key in _token_keys(att):
                    by_token.setdefault(key, att)

            pattern = re.compile(r"!\[\[att:([A-Za-z0-9_-]+)\]\]", re.IGNORECASE)

            def _replace(match: re.Match[str]) -> str:
                token = match.group(1)
                att = None
                if token.isdigit():
                    att = by_id.get(int(token))
                if not att:
                    token_lower = token.lower()
                    att = by_token.get(token_lower)
                if not att:
                    # Try stripping known extensions
                    for ext in (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"):
                        if token_lower.endswith(ext):
                            trimmed = token_lower[: -len(ext)]
                            att = by_token.get(trimmed) or by_token.get(slugify(trimmed))
                            if att:
                                break
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
