import json
from datetime import datetime, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q, Sum, Count
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from accounts.models import DEFAULT_USER_TIMEZONE, TeacherProfile, UserPreferences

from .forms import (
    LessonCreateForm,
    LessonSeriesCreateForm,
    LessonSeriesUpdateForm,
    RescheduleRequestForm,
    UserTimezoneForm,
)
from .models import Lesson, LessonPayment, LessonRescheduleRequest, LessonSeries
from .services import (
    cancel_lesson,
    complete_lesson,
    mark_no_show,
    record_payment,
    request_reschedule,
    resolve_reschedule,
    set_series_status,
    reschedule_lesson,
    reopen_lesson,
    unmark_payment,
    delete_lesson,
)


MOSCOW_TIMEZONE = ZoneInfo("Europe/Moscow")
WEEKDAY_SHORT_NAMES = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


def _dashboard_role(request) -> str:
    role = request.session.get("dashboard_role")
    return role if role in {"student", "teacher", "methodist"} else "student"


def _is_teacher(user) -> bool:
    return TeacherProfile.objects.filter(user=user).exists()


def _lessons_for_user(user):
    queryset = Lesson.objects.select_related(
        "teacher_student_link",
        "teacher_student_link__teacher",
        "teacher_student_link__student",
        "teacher_student_link__student_record",
        "teacher_student_link__student_record__user",
        "teacher_student_link__subject",
        "series",
        "payment",
    ).prefetch_related("reschedule_requests__requested_by").exclude(status=Lesson.Status.DELETED)
    if user.is_staff:
        return queryset
    return queryset.filter(
        Q(teacher_student_link__teacher=user)
        | Q(teacher_student_link__student_record__user=user)
        | Q(teacher_student_link__student=user)
    )


def _get_lesson_for_user(user, lesson_id: int) -> Lesson:
    return get_object_or_404(_lessons_for_user(user), pk=lesson_id)


def _get_series_for_teacher(user, series_id: int) -> LessonSeries:
    queryset = LessonSeries.objects.select_related(
        "teacher_student_link",
        "teacher_student_link__teacher",
        "teacher_student_link__student",
        "teacher_student_link__student_record",
        "teacher_student_link__student_record__user",
        "teacher_student_link__subject",
    )
    if not user.is_staff:
        queryset = queryset.filter(teacher_student_link__teacher=user)
    return get_object_or_404(queryset, pk=series_id)


def _viewer_timezone(user) -> tuple[UserPreferences, ZoneInfo]:
    preferences, _ = UserPreferences.objects.get_or_create(user=user)
    try:
        viewer_timezone = ZoneInfo(preferences.timezone)
    except (ValueError, KeyError):
        viewer_timezone = ZoneInfo(DEFAULT_USER_TIMEZONE)
    return preferences, viewer_timezone


def _parse_calendar_boundary(value: str, viewer_timezone: ZoneInfo) -> datetime:
    """Interpret a FullCalendar wall-clock value in the profile timezone."""
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    # Calendar events are deliberately emitted as floating local values. Ignore
    # the browser offset here so a profile set to Yekaterinburg keeps its date
    # boundaries even when the browser itself is running in another timezone.
    local_wall_time = parsed.replace(tzinfo=None, fold=0)
    return local_wall_time.replace(tzinfo=viewer_timezone).astimezone(datetime_timezone.utc)


def _format_lesson_rows(lessons, user) -> list[dict]:
    _, viewer_timezone = _viewer_timezone(user)

    rows = []
    for lesson in lessons:
        local_start = lesson.scheduled_start.astimezone(viewer_timezone)
        moscow_start = lesson.scheduled_start.astimezone(MOSCOW_TIMEZONE)
        pending_request = next(
            (
                item
                for item in lesson.reschedule_requests.all()
                if item.status == LessonRescheduleRequest.Status.PENDING
            ),
            None,
        )
        rows.append(
            {
                "lesson": lesson,
                "local_start": local_start.strftime("%d.%m.%Y %H:%M"),
                "moscow_start": moscow_start.strftime("%d.%m.%Y %H:%M"),
                "differs_from_moscow": (
                    local_start.replace(tzinfo=None) != moscow_start.replace(tzinfo=None)
                ),
                "pending_request": pending_request,
                "can_manage": user.is_staff
                or lesson.teacher_student_link.teacher_id == user.id,
                "can_reschedule": lesson.status == Lesson.Status.SCHEDULED
                and (pending_request is None or user.is_staff or lesson.teacher_student_link.teacher_id == user.id),
                "can_resolve": pending_request is not None
                and pending_request.requested_by_id != user.id,
                "payment": lesson.payment,
            }
        )
    return rows


@login_required
def calendar_events(request):
    """Return FullCalendar events visible to the current user."""
    start_value = request.GET.get("start", "")
    end_value = request.GET.get("end", "")
    if not start_value or not end_value:
        return JsonResponse({"error": "Укажите границы календаря start и end."}, status=400)

    preferences, viewer_timezone = _viewer_timezone(request.user)
    try:
        range_start = _parse_calendar_boundary(start_value, viewer_timezone)
        range_end = _parse_calendar_boundary(end_value, viewer_timezone)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Некорректный диапазон дат."}, status=400)
    if range_end <= range_start or range_end - range_start > timedelta(days=370):
        return JsonResponse({"error": "Некорректный диапазон дат."}, status=400)

    lessons = (
        _lessons_for_user(request.user)
        .exclude(status=Lesson.Status.CANCELLED, series__isnull=True,
                 cancellation_reason="Расписание серии изменено")
        .filter(scheduled_start__gte=range_start, scheduled_start__lt=range_end)
        .order_by("scheduled_start")
    )
    events = []
    for lesson in lessons:
        link = lesson.teacher_student_link
        local_start = lesson.scheduled_start.astimezone(viewer_timezone)
        local_end = lesson.scheduled_end.astimezone(viewer_timezone)
        pending_request = next(
            (
                item
                for item in lesson.reschedule_requests.all()
                if item.status == LessonRescheduleRequest.Status.PENDING
            ),
            None,
        )
        teacher_name = link.teacher.get_full_name() or link.teacher.username
        student_name = link.student_display_name
        if request.user.id == link.teacher_id:
            title = f"{student_name} · {link.subject.name}"
            counterpart_label = "Ученик"
            counterpart_name = student_name
        elif link.student_user and request.user.id == link.student_user.id:
            title = f"{link.subject.name} · {teacher_name}"
            counterpart_label = "Учитель"
            counterpart_name = teacher_name
        else:
            title = f"{student_name} · {link.subject.name}"
            counterpart_label = "Участники"
            counterpart_name = f"{teacher_name} / {student_name}"

        can_manage = request.user.is_staff or request.user.id == link.teacher_id
        can_reschedule = lesson.status == Lesson.Status.SCHEDULED and (pending_request is None or can_manage)
        events.append(
            {
                "id": str(lesson.id),
                "title": title,
                # Floating local values keep the selected profile timezone visible
                # even when the browser itself is configured for another timezone.
                "start": local_start.replace(tzinfo=None).isoformat(),
                "end": local_end.replace(tzinfo=None).isoformat(),
                "editable": can_reschedule,
                "durationEditable": False,
                "classNames": [
                    "lesson-event",
                    f"lesson-event--{lesson.status}",
                    f"lesson-event--payment-{lesson.payment.status}",
                ],
                "extendedProps": {
                    "subject": link.subject.name,
                    "counterpartLabel": counterpart_label,
                    "counterpartName": counterpart_name,
                    "teacher": teacher_name,
                    "student": student_name,
                    "status": lesson.status,
                    "statusLabel": lesson.get_status_display(),
                    "paymentStatus": lesson.payment.status,
                    "paymentLabel": lesson.payment.get_status_display(),
                    "price": f"{lesson.price_amount} {lesson.currency}",
                    "duration": lesson.duration_minutes,
                    "timezone": preferences.timezone,
                    "hasPendingReschedule": pending_request is not None,
                    "canReschedule": can_reschedule,
                    "canManage": can_manage,
                    "canDelete": can_manage and lesson.status == Lesson.Status.SCHEDULED
                    and lesson.payment.status == LessonPayment.Status.UNPAID,
                    "canMarkPaid": can_manage
                    and lesson.payment.status == LessonPayment.Status.UNPAID,
                    "rescheduleUrl": (
                        reverse("lessons:reschedule", args=[lesson.id])
                        if can_reschedule
                        else ""
                    ),
                    "calendarRescheduleUrl": (
                        reverse("lessons:calendar-reschedule", args=[lesson.id])
                        if can_reschedule
                        else ""
                    ),
                    "lessonActionUrl": reverse("lessons:lesson-action", args=[lesson.id]),
                    "seriesEditUrl": (
                        reverse("lessons:series-edit", args=[lesson.series_id])
                        if can_manage and lesson.series_id
                        else ""
                    ),
                    "cardId": f"lesson-card-{lesson.id}",
                },
            }
        )
    return JsonResponse(events, safe=False)


@require_POST
@login_required
def calendar_reschedule(request, lesson_id: int):
    lesson = _get_lesson_for_user(request.user, lesson_id)
    _, viewer_timezone = _viewer_timezone(request.user)
    try:
        payload = json.loads(request.body or b"{}")
        if not isinstance(payload, dict):
            raise ValueError
        proposed_start = _parse_calendar_boundary(
            str(payload.get("proposed_start", "")),
            viewer_timezone,
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({"error": "Укажите корректное новое время урока."}, status=400)

    try:
        if request.user.is_staff or lesson.teacher_student_link.teacher_id == request.user.id:
            reschedule_lesson(lesson=lesson, actor=request.user, proposed_start=proposed_start,
                              reason=str(payload.get("reason") or "Перенос из календаря").strip())
            return JsonResponse({"message": "Урок перенесён.", "rescheduled": True})
        change_request = request_reschedule(
            lesson=lesson,
            requested_by=request.user,
            proposed_start=proposed_start,
            reason=str(payload.get("reason") or "Перенос из календаря").strip(),
        )
    except ValidationError as exc:
        return JsonResponse({"error": "; ".join(exc.messages)}, status=400)
    except PermissionDenied as exc:
        return JsonResponse({"error": str(exc)}, status=403)
    return JsonResponse(
        {
            "request_id": change_request.id,
            "message": "Запрос на перенос отправлен и ожидает подтверждения.",
        },
        status=201,
    )


@ensure_csrf_cookie
@login_required
def schedule(request):
    now = timezone.now()
    queryset = _lessons_for_user(request.user)
    upcoming = list(
        queryset.filter(
            status=Lesson.Status.SCHEDULED,
            scheduled_start__gte=now,
        ).order_by("scheduled_start")[:100]
    )
    history_page = Paginator(
        queryset.filter(
            Q(scheduled_start__lt=now) | ~Q(status=Lesson.Status.SCHEDULED)
        )
        .order_by("-scheduled_start", "-pk"), 25
    ).get_page(request.GET.get("page"))
    preferences, viewer_timezone = _viewer_timezone(request.user)
    local_now = now.astimezone(viewer_timezone)
    month_start_local = local_now.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    if request.GET.get("month"):
        try:
            selected = datetime.strptime(request.GET["month"], "%Y-%m")
            if not 2000 <= selected.year <= 2100:
                raise ValueError
            month_start_local = month_start_local.replace(year=selected.year, month=selected.month)
        except ValueError:
            messages.error(request, "Укажите месяц в формате ГГГГ-ММ.")
    if month_start_local.month == 12:
        next_month_local = month_start_local.replace(
            year=month_start_local.year + 1,
            month=1,
        )
    else:
        next_month_local = month_start_local.replace(month=month_start_local.month + 1)
    billable = queryset.exclude(status=Lesson.Status.CANCELLED)
    unpaid = billable.filter(payment__status=LessonPayment.Status.UNPAID)
    paid_this_month = queryset.filter(
        payment__status=LessonPayment.Status.PAID,
        payment__paid_at__gte=month_start_local.astimezone(datetime_timezone.utc),
        payment__paid_at__lt=next_month_local.astimezone(datetime_timezone.utc),
    )
    payment_summary = {
        "unpaid_count": unpaid.count(),
        "unpaid_amounts": list(unpaid.order_by().values("payment__currency").annotate(
            total=Sum("payment__amount")
        ).order_by("payment__currency")),
        "paid_month_amounts": list(paid_this_month.order_by().values("payment__currency").annotate(
            total=Sum("payment__amount")
        ).order_by("payment__currency")),
    }
    month_lessons = queryset.filter(scheduled_start__gte=month_start_local,
                                    scheduled_start__lt=next_month_local)
    statistics = month_lessons.aggregate(
        planned=Count("id", filter=Q(status=Lesson.Status.SCHEDULED)),
        completed=Count("id", filter=Q(status=Lesson.Status.COMPLETED)),
        minutes=Sum("duration_minutes", filter=Q(status=Lesson.Status.COMPLETED)),
    )
    statistics["hours"], statistics["remaining_minutes"] = divmod(statistics["minutes"] or 0, 60)
    debt = queryset.filter(status=Lesson.Status.COMPLETED, payment__status=LessonPayment.Status.UNPAID)
    statistics["unpaid_completed"] = debt.count()
    statistics["debt_amounts"] = list(debt.order_by().values("payment__currency").annotate(
        total=Sum("payment__amount")
    ).order_by("payment__currency"))
    is_teacher = _is_teacher(request.user)
    series_rows = []
    if is_teacher:
        series = (
            LessonSeries.objects.filter(teacher_student_link__teacher=request.user)
            .select_related(
                "teacher_student_link__student",
                "teacher_student_link__student_record",
                "teacher_student_link__student_record__user",
                "teacher_student_link__subject",
            )
            .order_by("status", "local_time", "id")[:50]
        )
        for item in series:
            series_rows.append(
                {
                    "series": item,
                    "student_name": item.teacher_student_link.student_display_name,
                    "weekdays": ", ".join(WEEKDAY_SHORT_NAMES[day] for day in item.weekdays),
                }
            )
    context = {
        "active_tab": "lessons",
        "role": _dashboard_role(request),
        "is_teacher": is_teacher,
        "series_rows": series_rows,
        "payment_summary": payment_summary,
        "upcoming_rows": _format_lesson_rows(upcoming, request.user),
        "history_rows": _format_lesson_rows(history_page.object_list, request.user),
        "history_page": history_page,
        "statistics": statistics,
        "selected_month": month_start_local.strftime("%Y-%m"),
        "month_label": month_start_local,
        "preferences": preferences,
    }
    return render(request, "lessons/schedule.html", context)


@login_required
def lesson_create(request):
    if not _is_teacher(request.user):
        raise PermissionDenied("Создание урока доступно только учителю.")
    form = LessonCreateForm(request.POST or None, teacher=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            lesson = form.save()
        except (ValidationError, PermissionDenied) as exc:
            message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
            form.add_error(None, message)
        else:
            messages.success(request, f"Разовый урок №{lesson.id} создан.")
            return redirect("lessons:schedule")
    return render(
        request,
        "lessons/lesson_form.html",
        {"form": form, "active_tab": "lessons", "role": _dashboard_role(request)},
    )


@login_required
def series_create(request):
    if not _is_teacher(request.user):
        raise PermissionDenied("Создание расписания доступно только учителю.")
    form = LessonSeriesCreateForm(
        request.POST or None,
        teacher=request.user,
    )
    if request.method == "POST" and form.is_valid():
        try:
            series, report = form.save()
        except (ValidationError, PermissionDenied) as exc:
            message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
            form.add_error(None, message)
        else:
            messages.success(
                request,
                f"Расписание создано. Уроков добавлено: {report.created_count}; "
                f"конфликтов: {len(report.conflicts)}.",
            )
            return redirect("lessons:schedule")
    return render(
        request,
        "lessons/series_form.html",
        {
            "form": form,
            "active_tab": "lessons",
            "role": _dashboard_role(request),
        },
    )


@login_required
def series_edit(request, series_id: int):
    series = _get_series_for_teacher(request.user, series_id)
    form = LessonSeriesUpdateForm(
        request.POST or None,
        teacher=request.user,
        series=series,
    )
    if request.method == "POST" and form.is_valid():
        try:
            series, report = form.save()
        except (ValidationError, PermissionDenied) as exc:
            message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
            form.add_error(None, message)
        else:
            messages.success(
                request,
                "Серия обновлена. "
                f"Изменено уроков: {report.updated_count}; "
                f"перенесено: {report.moved_count}; "
                f"добавлено: {report.generation.created_count}; "
                f"отменено: {report.cancelled_count}; "
                f"конфликтов: {len(report.generation.conflicts)}.",
            )
            return redirect("lessons:schedule")
    return render(
        request,
        "lessons/series_form.html",
        {
            "form": form,
            "series": series,
            "is_edit": True,
            "active_tab": "lessons",
            "role": _dashboard_role(request),
        },
    )


@require_POST
@login_required
def series_action(request, series_id: int):
    series = _get_series_for_teacher(request.user, series_id)
    action = request.POST.get("action", "")
    try:
        series, cancelled_count = set_series_status(
            series=series,
            actor=request.user,
            action=action,
        )
    except (ValidationError, PermissionDenied) as exc:
        message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
        messages.error(request, message)
    else:
        if action == "end":
            messages.success(request, f"Серия завершена. Отменено будущих уроков: {cancelled_count}.")
        elif action == "pause":
            messages.success(request, "Автоматическое продолжение серии приостановлено.")
        else:
            messages.success(request, "Серия возобновлена.")
    return redirect("lessons:schedule")


@login_required
def reschedule_request(request, lesson_id: int):
    lesson = _get_lesson_for_user(request.user, lesson_id)
    can_manage = request.user.is_staff or lesson.teacher_student_link.teacher_id == request.user.id
    initial_start = timezone.localtime(lesson.scheduled_start).strftime("%Y-%m-%dT%H:%M")
    form = RescheduleRequestForm(
        request.POST or None,
        initial={"proposed_start": initial_start},
    )
    if request.method == "POST" and form.is_valid():
        try:
            operation = reschedule_lesson if can_manage else request_reschedule
            operation(lesson=lesson, proposed_start=form.cleaned_data["proposed_start"],
                      reason=form.cleaned_data["reason"],
                      **({"actor": request.user} if can_manage else {"requested_by": request.user}))
        except (ValidationError, PermissionDenied) as exc:
            message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
            form.add_error(None, message)
        else:
            messages.success(request, "Урок перенесён." if can_manage else "Запрос переноса отправлен.")
            return redirect("lessons:schedule")
    return render(
        request,
        "lessons/reschedule_form.html",
        {
            "lesson": lesson,
            "can_manage": can_manage,
            "form": form,
            "active_tab": "lessons",
            "role": _dashboard_role(request),
        },
    )


@require_POST
@login_required
def reschedule_resolve(request, request_id: int):
    change_request = get_object_or_404(
        LessonRescheduleRequest.objects.select_related(
            "lesson__teacher_student_link",
            "lesson__teacher_student_link__student_record",
            "lesson__teacher_student_link__student_record__user",
        ),
        pk=request_id,
    )
    if not request.user.is_staff and request.user.id not in {
        change_request.lesson.teacher_student_link.teacher_id,
        change_request.lesson.teacher_student_link.student_record.user_id
        or change_request.lesson.teacher_student_link.student_id,
    }:
        raise Http404
    try:
        resolve_reschedule(
            change_request=change_request,
            resolved_by=request.user,
            accept=request.POST.get("decision") == "accept",
        )
    except (ValidationError, PermissionDenied) as exc:
        message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
        messages.error(request, message)
    else:
        messages.success(request, "Решение по переносу сохранено.")
    return redirect("lessons:schedule")


@require_POST
@login_required
def lesson_action(request, lesson_id: int):
    lesson = _get_lesson_for_user(request.user, lesson_id)
    action = request.POST.get("action")
    try:
        if action == "complete":
            complete_lesson(
                lesson=lesson,
                actor=request.user,
                notes=(request.POST.get("notes") or "").strip(),
            )
        elif action == "cancel":
            cancel_lesson(
                lesson=lesson,
                actor=request.user,
                reason=(request.POST.get("reason") or "").strip(),
            )
        elif action == "no_show":
            mark_no_show(lesson=lesson, actor=request.user)
        elif action == "paid":
            record_payment(
                lesson=lesson,
                actor=request.user,
                method=request.POST.get("method") or LessonPayment.Method.BANK_TRANSFER,
            )
        elif action == "reopen":
            reopen_lesson(lesson=lesson, actor=request.user)
        elif action == "unpaid":
            unmark_payment(lesson=lesson, actor=request.user)
        elif action == "delete":
            delete_lesson(lesson=lesson, actor=request.user)
        else:
            raise ValidationError("Неизвестное действие.")
    except (ValidationError, PermissionDenied) as exc:
        message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
        messages.error(request, message)
    else:
        messages.success(request, "Изменения сохранены.")
    return redirect("lessons:schedule")


@login_required
def timezone_settings(request):
    preferences, _ = UserPreferences.objects.get_or_create(user=request.user)
    form = UserTimezoneForm(request.POST or None, instance=preferences)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Часовой пояс сохранен.")
        return redirect("lessons:schedule")
    return render(
        request,
        "lessons/timezone_form.html",
        {
            "form": form,
            "preferences": preferences,
            "active_tab": "lessons",
            "role": _dashboard_role(request),
        },
    )
