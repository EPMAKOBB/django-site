from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import urlencode
from django.utils.translation import gettext as _

from apps.recsys.models import SkillMastery, TypeMastery

from .models import Course, CourseGraphEdge, CourseEnrollment, CourseModule, CourseModuleItem


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

    if module.is_locked:
        raise Http404()

    enrollment = request.user.course_enrollments.filter(course=course).first()
    if enrollment is None:
        raise Http404()

    module_mastery_percent = _get_module_mastery_percent(request.user, module, enrollment)

    items = list(module.items.all())
    incoming = [edge for edge in course.graph_edges.all() if edge.dst_id == module.id]
    outgoing = [edge for edge in course.graph_edges.all() if edge.src_id == module.id]

    accessible_items = [
        item
        for item in items
        if item.min_mastery_percent <= module_mastery_percent <= item.max_mastery_percent
    ]

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

    if request.method == "POST" and current_item:
        action = request.POST.get("action") or ""
        target = current_item

        if action == "success":
            if next_item:
                messages.success(
                    request,
                    _("Элемент успешно завершён. Переходим к следующему."),
                )
                target = next_item
            else:
                messages.success(
                    request,
                    _("Элемент успешно завершён. Это последний доступный элемент."),
                )
        elif action == "failure":
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

        query = {"item": target.id} if target else {}
        redirect_url = module.get_absolute_url()
        if query:
            redirect_url = f"{redirect_url}?{urlencode(query)}"
        return redirect(redirect_url)

    items_with_state = []
    for index, item in enumerate(items, start=1):
        items_with_state.append(
            {
                "item": item,
                "position": index,
                "is_visible": item in accessible_items,
                "is_current": item == current_item,
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
    }
    return render(request, "courses/module_detail.html", context)


def _get_module_mastery_percent(user, module: CourseModule, enrollment: CourseEnrollment) -> float:
    mastery_value: float | None = None

    if module.kind == CourseModule.Kind.SKILL and module.skill_id:
        mastery_value = (
            SkillMastery.objects.filter(user=user, skill=module.skill)
            .values_list("mastery", flat=True)
            .first()
        )
    elif module.kind == CourseModule.Kind.TASK_TYPE and module.task_type_id:
        mastery_value = (
            TypeMastery.objects.filter(user=user, task_type=module.task_type)
            .values_list("mastery", flat=True)
            .first()
        )
    else:
        mastery_value = float(enrollment.progress or 0)

    if mastery_value is None:
        return 0.0

    mastery_percent = float(mastery_value)
    if mastery_percent <= 1.0:
        mastery_percent *= 100.0

    return max(0.0, min(100.0, mastery_percent))
