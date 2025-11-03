from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import urlencode
from django.utils.translation import gettext as _

from apps.recsys.forms import TaskAnswerForm, compare_answers
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

    task_answer_form: TaskAnswerForm | None = None
    task_correct_answer = None
    if (
        current_item
        and current_item.kind == current_item.ItemKind.TASK
        and current_item.task
    ):
        task_correct_answer = current_item.task.correct_answer or {}
        form_data = (
            request.POST
            if request.method == "POST"
            and (request.POST.get("action") or "") == "submit-answer"
            else None
        )
        task_answer_form = TaskAnswerForm(task_correct_answer, data=form_data)

    if request.method == "POST" and current_item:
        action = request.POST.get("action") or ""
        target = current_item
        should_redirect = True

        if action == "submit-answer":
            if (
                current_item.kind == current_item.ItemKind.TASK
                and current_item.task
            ):
                if not task_answer_form or not task_answer_form.is_available:
                    messages.error(
                        request,
                        _("Проверка ответа для этого задания пока недоступна."),
                    )
                elif task_answer_form.is_valid() and task_correct_answer is not None:
                    user_answer = task_answer_form.get_answer()
                    is_correct = compare_answers(task_correct_answer, user_answer)

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
                                _("Ответ верный! Переходим к следующей карточке."),
                            )
                            target = next_item
                        else:
                            messages.success(
                                request,
                                _("Ответ верный! Это была последняя карточка в модуле."),
                            )
                    else:
                        messages.error(
                            request,
                            _("Ответ неверный. Попробуй ещё раз."),
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
        "task_answer_form": task_answer_form,
        "task_answer_submit_label": _("Проверить ответ"),
        "task_answer_unavailable_message": _("Проверка ответа для этого задания пока недоступна."),
        "task_answer_legend": _("Ответ на задание"),
    }
    return render(request, "courses/module_detail.html", context)
