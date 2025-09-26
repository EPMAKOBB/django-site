from __future__ import annotations

from typing import Iterable

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext as _

from apps.recsys.models import SkillMastery, TypeMastery

from .models import Course, CourseEnrollment, CourseModule, CourseModuleItem


def _determine_dashboard_role(request) -> str:
    """Return the dashboard role stored in the session (defaults to ``student``)."""

    role = request.session.get("dashboard_role")
    if role in {"student", "teacher"}:
        return role
    request.session["dashboard_role"] = "student"
    return "student"


def _module_mastery_percent(enrollment: CourseEnrollment, module: CourseModule) -> float:
    """Return the user's mastery for the given module as a percentage."""

    user = enrollment.student
    mastery_percent = 0.0

    if module.kind == CourseModule.Kind.SKILL and module.skill_id:
        mastery = SkillMastery.objects.filter(user=user, skill=module.skill).first()
        if mastery is not None:
            mastery_percent = float(mastery.mastery) * 100
    elif module.kind == CourseModule.Kind.TASK_TYPE and module.task_type_id:
        mastery = TypeMastery.objects.filter(user=user, task_type=module.task_type).first()
        if mastery is not None:
            mastery_percent = float(mastery.mastery) * 100
    else:
        mastery_percent = float(enrollment.progress or 0)

    return max(0.0, min(100.0, mastery_percent))


def _select_current_item(
    items: Iterable[CourseModuleItem], mastery_percent: float
) -> CourseModuleItem | None:
    """Return the module item that should be presented to the learner."""

    items_list = list(items)
    for item in items_list:
        if item.min_mastery_percent <= mastery_percent <= item.max_mastery_percent:
            return item
    if not items_list:
        return None
    if mastery_percent < items_list[0].min_mastery_percent:
        return items_list[0]
    return items_list[-1]


@login_required
def module_detail(request, course_slug: str, module_slug: str):
    """Display the current learning item for a course module."""

    course = get_object_or_404(
        Course.objects.select_related("layout").prefetch_related("modules"),
        slug=course_slug,
        is_active=True,
    )

    enrollment = CourseEnrollment.objects.filter(
        course=course, student=request.user
    ).select_related("course", "student").first()
    if enrollment is None:
        raise PermissionDenied("Вы не записаны на этот курс.")

    module_qs = CourseModule.objects.select_related("course", "skill", "task_type").prefetch_related(
        Prefetch(
            "items",
            queryset=CourseModuleItem.objects.select_related("theory_card", "task").order_by(
                "position", "pk"
            ),
        )
    )
    module = get_object_or_404(module_qs, course=course, slug=module_slug)

    if module.is_locked:
        raise PermissionDenied("Этот модуль ещё закрыт.")

    submission_feedback: dict[str, str] | None = None
    if request.method == "POST":
        result = request.POST.get("result")
        if result == "success":
            submission_feedback = {
                "level": "success",
                "message": _("Результат сохранён. Если вы готовы, переходите к следующему элементу."),
            }
        elif result == "retry":
            submission_feedback = {
                "level": "info",
                "message": _("Мы отметили, что нужно повторить этот материал."),
            }
        else:
            submission_feedback = {
                "level": "warning",
                "message": _("Выберите доступное действие, чтобы продолжить."),
            }

    items = list(module.items.all())
    mastery_percent = _module_mastery_percent(enrollment, module)
    current_item = _select_current_item(items, mastery_percent)
    current_item_state = None
    if current_item is not None:
        if mastery_percent < current_item.min_mastery_percent:
            current_item_state = "locked"
        elif mastery_percent > current_item.max_mastery_percent:
            current_item_state = "completed"
        else:
            current_item_state = "current"

    item_states: list[dict[str, object]] = []
    current_index = -1
    if current_item is not None:
        try:
            current_index = items.index(current_item)
        except ValueError:
            current_index = -1

    previous_item = items[current_index - 1] if current_index > 0 else None
    next_item = items[current_index + 1] if current_index >= 0 and current_index + 1 < len(items) else None
    previous_state = None
    next_state = None

    for index, item in enumerate(items):
        if mastery_percent < item.min_mastery_percent:
            state = "locked"
        elif mastery_percent > item.max_mastery_percent:
            state = "completed"
        else:
            state = "available"
        if index == current_index:
            state = "current" if state == "available" else state
        item_states.append({"object": item, "state": state})
        if item is previous_item:
            previous_state = state
        if item is next_item:
            next_state = state

    context = {
        "active_tab": "courses",
        "role": _determine_dashboard_role(request),
        "course": course,
        "module": module,
        "enrollment": enrollment,
        "module_mastery_percent": mastery_percent,
        "current_item": current_item,
        "current_item_state": current_item_state,
        "previous_item": previous_item,
        "previous_item_state": previous_state,
        "next_item": next_item,
        "next_item_state": next_state,
        "item_states": item_states,
        "sibling_modules": list(course.modules.all()),
        "submission_feedback": submission_feedback,
    }
    return render(request, "courses/module_detail.html", context)
