from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import urlencode
from django.utils.translation import gettext as _

from apps.recsys.models import Attempt

from .models import (
    Course,
    CourseEnrollment,
    CourseGraphEdge,
    CourseModule,
    CourseModuleItem,
    CourseModuleItemCompletion,
)
from .services import calculate_module_progress_percent, is_module_unlocked_for_user
from apps.recsys.service_utils.type_progress import build_type_progress_map


@dataclass(frozen=True)
class AnswerSegment:
    kind: str  # "dict" or "list"
    key: Any


@dataclass
class AnswerField:
    name: str
    label: str
    segments: tuple[AnswerSegment, ...]
    value_type: str
    widget: str
    input_type: str | None = None
    step: str | None = None
    choices: tuple[tuple[str, str], ...] = ()
    value: str = ""


def _detect_value_type(sample: Any) -> str:
    if isinstance(sample, bool):
        return "boolean"
    if isinstance(sample, int):
        return "integer"
    if isinstance(sample, float):
        return "float"
    return "string"


def _format_answer_label(segments: tuple[AnswerSegment, ...]) -> str:
    parts = [_("Ответ")]
    for segment in segments:
        if segment.kind == "dict":
            parts.append(str(segment.key))
        else:
            index = int(segment.key) + 1
            parts.append(_("элемент %(index)s") % {"index": index})
    return " → ".join(parts)


def _build_field_name(segments: tuple[AnswerSegment, ...]) -> str:
    if not segments:
        return "answer__value"
    tokens = [str(segment.key) for segment in segments]
    return "answer__" + "__".join(tokens)


def _build_answer_fields(correct_answer: Any) -> list[AnswerField]:
    fields: list[AnswerField] = []

    def _make_field(sample_value: Any, segments: tuple[AnswerSegment, ...]) -> AnswerField:
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

        return AnswerField(
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
        fields.append(_make_field(correct_answer, tuple()))

    return fields


def _convert_answer_value(field: AnswerField, raw_value: str) -> Any:
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
            _("Выберите одно из допустимых значений для поля «%(label)s».")
            % {"label": field.label}
        )

    return value


def _initial_structure(template: Any) -> Any:
    if isinstance(template, dict):
        return {}
    if isinstance(template, list):
        return []
    return None


def _insert_value(target: Any, segments: tuple[AnswerSegment, ...], value: Any) -> None:
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


def _assemble_answer_structure(
    template: Any, fields: Sequence[AnswerField], converted: dict[str, Any]
) -> Any:
    base = _initial_structure(template)
    if base is None:
        field = fields[0] if fields else None
        return converted.get(field.name) if field else None

    for field in fields:
        _insert_value(base, field.segments, converted[field.name])
    return base


def _compare_answers(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or expected.keys() != actual.keys():
            return False
        return all(_compare_answers(expected[key], actual[key]) for key in expected)
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return False
        return all(_compare_answers(exp, act) for exp, act in zip(expected, actual))
    if isinstance(expected, str):
        return expected.strip().casefold() == str(actual).strip().casefold()
    if isinstance(expected, float):
        try:
            actual_value = float(actual)
        except (TypeError, ValueError):
            return False
        return abs(expected - actual_value) <= 1e-9
    return expected == actual


@login_required
def module_detail(request, course_slug: str, module_slug: str):
    course = get_object_or_404(
        Course.objects.prefetch_related(
            Prefetch(
                "modules",
                queryset=CourseModule.objects.order_by("rank", "col", "id"),
            ),
            Prefetch(
                "graph_edges",
                queryset=CourseGraphEdge.objects.select_related("src", "dst"),
            ),
        ),
        slug=course_slug,
        is_active=True,
    )

    module = get_object_or_404(
        course.modules.prefetch_related(
            Prefetch(
                "items",
                queryset=CourseModuleItem.objects.select_related("theory_card", "task")
                .order_by("position", "id"),
            ),
        ),
        slug=module_slug,
    )

    course_modules = list(course.modules.all())
    course_task_type_ids = {
        m.task_type_id
        for m in course_modules
        if m.kind == CourseModule.Kind.TASK_TYPE and m.task_type_id
    }
    course_type_progress_map = (
        build_type_progress_map(user=request.user, task_type_ids=course_task_type_ids)
        if course_task_type_ids
        else {}
    )

    enrollment = request.user.course_enrollments.filter(course=course).first()
    if enrollment is None:
        raise Http404()

    items = list(module.items.all())
    incoming = [edge for edge in course.graph_edges.all() if edge.dst_id == module.id]
    outgoing = [edge for edge in course.graph_edges.all() if edge.src_id == module.id]

    if not is_module_unlocked_for_user(
        user=request.user,
        module=module,
        enrollment=enrollment,
        incoming_edges=incoming,
        type_progress_map=course_type_progress_map,
    ):
        raise Http404()

    theory_item_ids = [item.id for item in items if item.kind == item.ItemKind.THEORY]
    completed_theory_item_ids: set[int] = set()
    if theory_item_ids:
        completed_theory_item_ids = set(
            CourseModuleItemCompletion.objects.filter(
                user=request.user, module_item_id__in=theory_item_ids
            ).values_list("module_item_id", flat=True)
        )

    module_mastery_percent = calculate_module_progress_percent(
        user=request.user,
        module=module,
        enrollment=enrollment,
        module_items=items,
        completed_theory_item_ids=completed_theory_item_ids,
        type_progress_map=course_type_progress_map,
    )

    def _build_accessible_items(current_mastery: float) -> list[CourseModuleItem]:
        return [
            item
            for item in items
            if item.min_mastery_percent <= current_mastery <= item.max_mastery_percent
        ]

    accessible_items = _build_accessible_items(module_mastery_percent)

    requested_item_id = request.GET.get("item") or request.POST.get("item_id")

    def _get_item_by_id(item_id: str | None) -> CourseModuleItem | None:
        if not item_id:
            return None
        for item in items:
            if str(item.id) == str(item_id):
                return item
        return None

    current_item = None
    if requested_item_id:
        candidate = _get_item_by_id(requested_item_id)
        if candidate and candidate in accessible_items:
            current_item = candidate

    if current_item is None:
        if accessible_items:
            current_item = accessible_items[0]
        elif items:
            current_item = items[0]

    def _find_neighbor(
        source: CourseModuleItem | None, step: int
    ) -> CourseModuleItem | None:
        if source is None or source not in items:
            return None
        index = items.index(source)
        while 0 <= index + step < len(items):
            index += step
            candidate = items[index]
            if candidate in accessible_items:
                return candidate
        return None

    previous_item = _find_neighbor(current_item, -1)
    next_item = _find_neighbor(current_item, 1)

    task_answer_fields: list[AnswerField] = []
    task_answer_values: dict[str, str] = {}
    task_answer_errors: list[str] = []
    task_answer_check_available = False
    task_correct_answer: Any | None = None
    if (
        current_item
        and current_item.kind == current_item.ItemKind.TASK
        and current_item.task
    ):
        task_correct_answer = current_item.task.correct_answer or {}
        task_answer_fields = _build_answer_fields(task_correct_answer)
        task_answer_check_available = bool(task_answer_fields)

    if request.method == "POST" and current_item:
        action = request.POST.get("action") or ""
        target = current_item
        should_redirect = True

        if action == "submit-answer":
            if (
                current_item.kind == current_item.ItemKind.TASK
                and current_item.task
            ):
                if not task_answer_check_available:
                    messages.error(
                        request,
                        _("Проверка ответа для этого задания пока недоступна."),
                    )
                else:
                    task_answer_values = {
                        field.name: (request.POST.get(field.name) or "").strip()
                        for field in task_answer_fields
                    }
                    converted_values: dict[str, Any] = {}
                    for field in task_answer_fields:
                        try:
                            converted_values[field.name] = _convert_answer_value(
                                field, task_answer_values[field.name]
                            )
                        except ValueError as exc:
                            task_answer_errors.append(str(exc))

                    if not task_answer_errors and task_correct_answer is not None:
                        user_answer = _assemble_answer_structure(
                            task_correct_answer, task_answer_fields, converted_values
                        )
                        is_correct = _compare_answers(task_correct_answer, user_answer)

                        Attempt.objects.create(
                            user=request.user,
                            task=current_item.task,
                            is_correct=is_correct,
                        )

                        module_mastery_percent = calculate_module_progress_percent(
                            user=request.user,
                            module=module,
                            enrollment=enrollment,
                            module_items=items,
                            completed_theory_item_ids=completed_theory_item_ids,
                        )
                        accessible_items = _build_accessible_items(module_mastery_percent)
                        previous_item = _find_neighbor(current_item, -1)
                        next_item = _find_neighbor(current_item, 1)

                        if is_correct:
                            if next_item:
                                messages.success(
                                    request,
                                    _("Ответ верный! Переходим к следующему заданию."),
                                )
                                target = next_item
                            else:
                                messages.success(
                                    request,
                                    _("Ответ верный! Это было последнее задание в модуле."),
                                )
                        else:
                            messages.error(
                                request,
                                _("Ответ неверный. Попробуйте ещё раз."),
                            )

                        query = {"item": target.id} if target else {}
                        redirect_url = module.get_absolute_url()
                        if query:
                            redirect_url = f"{redirect_url}?{urlencode(query)}"
                        return redirect(redirect_url)
                    else:
                        should_redirect = False
            else:
                messages.error(
                    request,
                    _("Проверка ответа недоступна для этого элемента."),
                )
            action = None

        if (
            action in {"success", "failure"}
            and current_item.kind == current_item.ItemKind.THEORY
            and current_item.id in theory_item_ids
        ):
            if action == "success" and current_item.id not in completed_theory_item_ids:
                CourseModuleItemCompletion.objects.get_or_create(
                    user=request.user, module_item=current_item
                )
                completed_theory_item_ids.add(current_item.id)
            elif action == "failure" and current_item.id in completed_theory_item_ids:
                CourseModuleItemCompletion.objects.filter(
                    user=request.user, module_item=current_item
                ).delete()
                completed_theory_item_ids.remove(current_item.id)

            module_mastery_percent = calculate_module_progress_percent(
                user=request.user,
                module=module,
                enrollment=enrollment,
                module_items=items,
                completed_theory_item_ids=completed_theory_item_ids,
            )
            accessible_items = _build_accessible_items(module_mastery_percent)

        previous_item = _find_neighbor(current_item, -1)
        next_item = _find_neighbor(current_item, 1)

        if action == "success":
            if current_item not in accessible_items and next_item:
                target = next_item
            if next_item:
                messages.success(
                    request,
                    _("Карточка отмечена как пройденная. Можно переходить к следующей карточке."),
                )
                target = next_item
            else:
                messages.success(
                    request,
                    _("Карточка отмечена как пройденной. Это была последняя карточка в модуле."),
                )
        elif action == "failure":
            if current_item not in accessible_items and previous_item:
                target = previous_item
            if previous_item:
                messages.warning(
                    request,
                    _("Попробуйте ещё раз предыдущий элемент."),
                )
                target = previous_item
            else:
                messages.warning(
                    request,
                    _("Предыдущие элементы недоступны. Продолжайте с текущего."),
                )
        elif action == "previous" and previous_item:
            target = previous_item
        elif action == "next" and next_item:
            target = next_item

        if should_redirect:
            query = {"item": target.id} if target else {}
            redirect_url = module.get_absolute_url()
            if query:
                redirect_url = f"{redirect_url}?{urlencode(query)}"
            return redirect(redirect_url)

    for field in task_answer_fields:
        field.value = task_answer_values.get(field.name, "")

    task_ids = [item.task_id for item in items if item.task_id]
    attempts_by_task: dict[int, list[Attempt]] = {}
    if task_ids:
        for attempt in (
            Attempt.objects.filter(user=request.user, task_id__in=task_ids)
            .order_by("task_id", "-created_at")
        ):
            attempts_by_task.setdefault(attempt.task_id, []).append(attempt)

    items_with_state = []
    for index, item in enumerate(items, start=1):
        status = "neutral"
        if item.kind == item.ItemKind.TASK and item.task_id:
            item_attempts = attempts_by_task.get(item.task_id, [])
            if any(attempt.is_correct for attempt in item_attempts):
                status = "correct"
            elif item_attempts:
                status = "incorrect"
            else:
                status = "pending"
        elif item.kind == item.ItemKind.THEORY:
            status = "correct" if item.id in completed_theory_item_ids else "pending"

        items_with_state.append(
            {
                "item": item,
                "position": index,
                "is_visible": item in accessible_items,
                "is_current": item == current_item,
                "status": status,
            }
        )

    context = {
        "course": course,
        "module": module,
        "incoming_edges": incoming,
        "outgoing_edges": outgoing,
        "items": items,
        "items_with_state": items_with_state,
        "current_item": current_item,
        "current_item_accessible": current_item in accessible_items if current_item else False,
        "previous_item": previous_item,
        "next_item": next_item,
        "module_mastery_percent": module_mastery_percent,
        "task_answer_fields": task_answer_fields,
        "task_answer_values": task_answer_values,
        "task_answer_errors": task_answer_errors,
        "task_answer_check_available": task_answer_check_available,
    }
    return render(request, "courses/module_detail.html", context)
