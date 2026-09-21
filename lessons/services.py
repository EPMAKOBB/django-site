from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import TeacherStudentLink
from students.models import StudentRecord

from .models import (
    Lesson,
    LessonEvent,
    LessonPayment,
    LessonRescheduleRequest,
    LessonSeries,
)


ACTIVE_LESSON_STATUSES = (Lesson.Status.SCHEDULED,)


@dataclass
class ScheduleConflict:
    scheduled_start: datetime
    message: str


@dataclass
class GenerationReport:
    generated_from: date | None = None
    generated_through: date | None = None
    created: list[Lesson] = field(default_factory=list)
    conflicts: list[ScheduleConflict] = field(default_factory=list)

    @property
    def created_count(self) -> int:
        return len(self.created)


@dataclass
class SeriesUpdateReport:
    updated_count: int = 0
    moved_count: int = 0
    cancelled_count: int = 0
    generation: GenerationReport = field(default_factory=GenerationReport)


def _link_users(link: TeacherStudentLink) -> tuple[int, ...]:
    student_user_id = link.student_record.user_id or link.student_id
    return tuple(user_id for user_id in (link.teacher_id, student_user_id) if user_id)


def _lock_users(user_ids) -> None:
    list(
        get_user_model()
        .objects.select_for_update()
        .filter(pk__in=sorted(set(user_ids)))
        .order_by("pk")
        .values_list("pk", flat=True)
    )


def _lock_participants(link: TeacherStudentLink) -> None:
    _lock_users(_link_users(link))
    list(StudentRecord.objects.select_for_update().filter(pk=link.student_record_id))


def _assert_active_link(link: TeacherStudentLink) -> None:
    if link.status != TeacherStudentLink.Status.ACTIVE:
        raise ValidationError("Урок можно создать только для активной связи учителя и ученика.")


def _assert_participant(lesson: Lesson, actor) -> None:
    participant_ids = _link_users(lesson.teacher_student_link)
    if not actor or not actor.is_authenticated:
        raise PermissionDenied("Требуется авторизация.")
    if not actor.is_staff and actor.id not in participant_ids:
        raise PermissionDenied("Пользователь не является участником урока.")


def _assert_teacher(lesson: Lesson, actor) -> None:
    if not actor or not actor.is_authenticated:
        raise PermissionDenied("Требуется авторизация.")
    if not actor.is_staff and actor.id != lesson.teacher_student_link.teacher_id:
        raise PermissionDenied("Действие доступно только учителю.")


def _assert_series_teacher(series: LessonSeries, actor) -> None:
    if not actor or not actor.is_authenticated:
        raise PermissionDenied("Требуется авторизация.")
    if not actor.is_staff and actor.id != series.teacher_student_link.teacher_id:
        raise PermissionDenied("Управлять серией может только её учитель.")


def find_schedule_conflicts(
    *,
    link: TeacherStudentLink,
    scheduled_start: datetime,
    duration_minutes: int,
    exclude_lesson_id: int | None = None,
) -> list[Lesson]:
    if timezone.is_naive(scheduled_start):
        raise ValidationError("Время урока должно содержать часовой пояс.")
    scheduled_end = scheduled_start + timedelta(minutes=duration_minutes)
    candidates = (
        Lesson.objects.filter(
            status__in=ACTIVE_LESSON_STATUSES,
            scheduled_start__lt=scheduled_end,
        )
        .filter(
            Q(teacher_student_link__teacher_id=link.teacher_id)
            | Q(teacher_student_link__student_record_id=link.student_record_id)
        )
        .select_related("teacher_student_link")
    )
    if exclude_lesson_id:
        candidates = candidates.exclude(pk=exclude_lesson_id)
    return [item for item in candidates if item.scheduled_end > scheduled_start]


def _record_event(lesson: Lesson, event_type: str, actor=None, **payload) -> LessonEvent:
    return LessonEvent.objects.create(
        lesson=lesson,
        event_type=event_type,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        payload=payload,
    )


def _close_pending_reschedules(lesson: Lesson, actor) -> None:
    now = timezone.now()
    LessonRescheduleRequest.objects.filter(
        lesson=lesson,
        status=LessonRescheduleRequest.Status.PENDING,
    ).update(
        status=LessonRescheduleRequest.Status.CANCELLED,
        resolved_by=actor,
        resolved_at=now,
        updated_at=now,
    )


@transaction.atomic
def create_lesson(
    *,
    link: TeacherStudentLink,
    scheduled_start: datetime,
    duration_minutes: int,
    price_amount: Decimal,
    currency: str = "RUB",
    created_by=None,
    series: LessonSeries | None = None,
) -> Lesson:
    link = TeacherStudentLink.objects.select_related(
        "teacher", "student", "student_record", "student_record__user", "subject"
    ).get(pk=link.pk)
    _assert_active_link(link)
    if created_by and not created_by.is_staff and created_by.id != link.teacher_id:
        raise PermissionDenied("Создавать урок может только учитель.")
    if series and series.teacher_student_link_id != link.id:
        raise ValidationError("Серия относится к другой связи учителя и ученика.")
    _lock_participants(link)
    conflicts = find_schedule_conflicts(
        link=link,
        scheduled_start=scheduled_start,
        duration_minutes=duration_minutes,
    )
    if conflicts:
        raise ValidationError("Время пересекается с другим уроком учителя или ученика.")

    lesson = Lesson(
        teacher_student_link=link,
        series=series,
        scheduled_start=scheduled_start,
        duration_minutes=duration_minutes,
        price_amount=price_amount,
        currency=currency,
        created_by=created_by,
    )
    lesson.full_clean()
    lesson.save()
    return lesson


@transaction.atomic
def create_series(
    *,
    link: TeacherStudentLink,
    weekdays: list[int],
    local_time: time,
    timezone_name: str,
    start_date: date,
    end_date: date | None,
    duration_minutes: int,
    price_amount: Decimal,
    currency: str = "RUB",
    created_by=None,
    generation_horizon_weeks: int = 12,
    generate_now: bool = True,
) -> tuple[LessonSeries, GenerationReport]:
    _assert_active_link(link)
    if created_by and not created_by.is_staff and created_by.id != link.teacher_id:
        raise PermissionDenied("Создавать серию может только учитель.")
    series = LessonSeries(
        teacher_student_link=link,
        weekdays=weekdays,
        local_time=local_time,
        timezone=timezone_name,
        start_date=start_date,
        end_date=end_date,
        duration_minutes=duration_minutes,
        price_amount=price_amount,
        currency=currency,
        created_by=created_by,
        generation_horizon_weeks=generation_horizon_weeks,
    )
    series.full_clean()
    series.save()
    if not generate_now:
        return series, GenerationReport()
    report = generate_series_occurrences(series)
    series.refresh_from_db()
    return series, report


@transaction.atomic
def update_series(
    *, series: LessonSeries, link: TeacherStudentLink, weekdays: list[int],
    local_time: time, timezone_name: str, start_date: date, end_date: date | None,
    duration_minutes: int, price_amount: Decimal, actor,
) -> tuple[LessonSeries, SeriesUpdateReport]:
    """Move future occurrences in place, preserving their payments and notes."""
    series = LessonSeries.objects.select_for_update(of=("self",)).select_related(
        "teacher_student_link", "teacher_student_link__student_record"
    ).get(pk=series.pk)
    _assert_series_teacher(series, actor)
    _assert_active_link(link)
    if link.teacher_id != series.teacher_student_link.teacher_id:
        raise PermissionDenied("Нельзя передать серию другому учителю.")
    old_link = series.teacher_student_link
    _lock_users((*_link_users(old_link), *_link_users(link)))
    list(StudentRecord.objects.select_for_update().filter(
        pk__in=sorted({old_link.student_record_id, link.student_record_id})
    ).order_by("pk"))
    old_days, old_time, old_zone = set(series.weekdays), series.local_time, series.tzinfo
    old_start, old_end = series.start_date, series.end_date
    old_through = series.generated_through or (old_start - timedelta(days=1))
    series.teacher_student_link = link
    series.weekdays, series.local_time, series.timezone = weekdays, local_time, timezone_name
    series.start_date, series.end_date = start_date, end_date
    series.duration_minutes, series.price_amount = duration_minutes, price_amount
    series.full_clean()
    now = timezone.now()
    today = now.astimezone(series.tzinfo).date()
    new_days = set(series.weekdays)
    shared = old_days & new_days
    # Shared days keep their identity: Tue+Thu -> Mon+Thu only moves Tuesday.
    day_map = {day: day for day in shared}
    day_map.update(zip(sorted(old_days - new_days), sorted(new_days - old_days)))
    added_days = new_days - set(day_map.values())
    lessons = list(Lesson.objects.select_for_update(of=("self",)).filter(
        series=series, status=Lesson.Status.SCHEDULED, scheduled_start__gte=now
    ).order_by("scheduled_start", "pk"))
    ids = [lesson.pk for lesson in lessons]
    payments = {p.lesson_id: p for p in LessonPayment.objects.select_for_update().filter(lesson_id__in=ids)}
    moves, cancellations, modified, events, payment_updates = [], [], [], [], []
    for lesson in lessons:
        original = lesson.scheduled_start
        local = original.astimezone(old_zone)
        target = original
        # Individually negotiated exceptions keep their current date and time.
        regular = local.weekday() in old_days and local.time() == old_time
        remove = False
        if regular:
            mapped = day_map.get(local.weekday())
            if mapped is None:
                remove = True
            else:
                target_date = local.date() + timedelta(days=mapped - local.weekday())
                target = _localize_series_start(series, target_date).astimezone(datetime_timezone.utc)
                # Do not move this week's lesson into the past or before the series began.
                if target < now or target_date < start_date:
                    target = original
        target_date = target.astimezone(series.tzinfo).date()
        remove = remove or target_date < start_date or (end_date is not None and target_date > end_date)
        payment = payments[lesson.pk]
        if payment.status == LessonPayment.Status.PAID and (remove or old_link.pk != link.pk):
            raise ValidationError("Изменение убирает оплаченный урок или передаёт его другому ученику. Перенесите этот урок отдельно.")
        if remove:
            lesson.status = Lesson.Status.CANCELLED
            lesson.cancelled_at = now
            lesson.cancellation_reason = "Сокращён период или количество занятий серии"
            cancellations.append(lesson)
            events.append(LessonEvent(lesson=lesson, actor=actor, event_type=LessonEvent.Type.CANCELLED,
                                      payload={"reason": lesson.cancellation_reason}))
        else:
            lesson.scheduled_start = target
            if target != original:
                moves.append(lesson)
                events.append(LessonEvent(lesson=lesson, actor=actor, event_type=LessonEvent.Type.RESCHEDULED,
                                          payload={"original_start": original.isoformat(), "scheduled_start": target.isoformat(),
                                                   "reason": "Изменено расписание серии", "series_id": series.pk}))
        changed = remove or target != original or lesson.teacher_student_link_id != link.pk or (
            lesson.duration_minutes != duration_minutes or lesson.price_amount != price_amount
        )
        if changed:
            lesson.teacher_student_link = link
            lesson.duration_minutes, lesson.price_amount = duration_minutes, price_amount
            lesson.updated_at = now
            modified.append(lesson)
            if not remove and payment.status == LessonPayment.Status.UNPAID and payment.amount != price_amount:
                payment.amount, payment.updated_at = price_amount, now
                payment_updates.append(payment)

    planned = sorted((lesson for lesson in lessons if lesson.status == Lesson.Status.SCHEDULED), key=lambda item: item.scheduled_start)
    for previous, current in zip(planned, planned[1:]):
        if previous.scheduled_end > current.scheduled_start:
            raise ValidationError("После изменения уроки серии пересекаются. Изменения не сохранены.")
    if planned:
        external = list(Lesson.objects.filter(status=Lesson.Status.SCHEDULED,
            scheduled_start__lt=max(item.scheduled_end for item in planned)).exclude(pk__in=ids).filter(
            Q(teacher_student_link__teacher_id=link.teacher_id) |
            Q(teacher_student_link__student_record_id=link.student_record_id)
        ))
        for lesson in planned:
            if any(other.scheduled_end > lesson.scheduled_start and other.scheduled_start < lesson.scheduled_end for other in external):
                local = lesson.scheduled_start.astimezone(series.tzinfo)
                raise ValidationError(f"Время {local:%d.%m.%Y %H:%M} занято другим уроком. Изменения не сохранены.")
        if Lesson.objects.filter(series=series, scheduled_start__in=[item.scheduled_start for item in planned]).exclude(pk__in=ids).exists():
            raise ValidationError("В серии уже есть запись на выбранное время. Изменения не сохранены.")

    series.save()
    # Temporarily detach moved rows inside this transaction to allow time swaps
    # without violating the unique (series, start) constraint mid-update.
    if moves:
        Lesson.objects.filter(pk__in=[item.pk for item in moves]).update(series=None)
    if modified:
        Lesson.objects.bulk_update(modified, ["series", "teacher_student_link", "scheduled_start", "duration_minutes",
            "price_amount", "status", "cancelled_at", "cancellation_reason", "updated_at"])
    if payment_updates:
        LessonPayment.objects.bulk_update(payment_updates, ["amount", "updated_at"])
    changed_ids = [item.pk for item in moves + cancellations]
    if old_link.pk != link.pk:
        changed_ids = ids
        Lesson.objects.filter(series=series).exclude(teacher_student_link=link).update(series=None)
    LessonRescheduleRequest.objects.filter(lesson_id__in=changed_ids, status=LessonRescheduleRequest.Status.PENDING).update(
        status=LessonRescheduleRequest.Status.CANCELLED, resolved_by=actor, resolved_at=now, updated_at=now)
    LessonEvent.objects.bulk_create(events)
    report = SeriesUpdateReport(updated_count=len(modified) - len(cancellations),
                                moved_count=len(moves), cancelled_count=len(cancellations))
    # Existing dates are not regenerated: that would recreate cancelled or
    # individually moved occurrences. Add only newly introduced days/periods.
    last_date = (max(old_through, _series_target_date(series, None))
                 if series.status == LessonSeries.Status.ACTIVE else old_through)
    if end_date:
        last_date = min(last_date, end_date)
    current = max(today, start_date)
    report.generation.generated_from, report.generation.generated_through = current, last_date
    while current <= last_date:
        newly_included = current > old_through or current < old_start or (old_end is not None and current > old_end)
        if current.weekday() in new_days and (newly_included or current.weekday() in added_days):
            target = _localize_series_start(series, current).astimezone(datetime_timezone.utc)
            if target >= now and not series.lessons.filter(scheduled_start=target).exists():
                lesson = create_lesson(link=link, scheduled_start=target, duration_minutes=duration_minutes,
                    price_amount=price_amount, currency=series.currency, created_by=actor, series=series)
                report.generation.created.append(lesson)
        current += timedelta(days=1)
    series.generated_through = last_date
    series.save(update_fields=["generated_through", "updated_at"])
    return series, report


@transaction.atomic
def set_series_status(*, series: LessonSeries, actor, action: str) -> tuple[LessonSeries, int]:
    series = LessonSeries.objects.select_for_update().select_related(
        "teacher_student_link"
    ).get(pk=series.pk)
    _assert_series_teacher(series, actor)
    if action == "pause":
        series.status = LessonSeries.Status.PAUSED
        series.save(update_fields=["status", "updated_at"])
        return series, 0
    if action == "resume":
        series.status = LessonSeries.Status.ACTIVE
        series.save(update_fields=["status", "updated_at"])
        generate_series_occurrences(series)
        series.refresh_from_db()
        return series, 0
    if action != "end":
        raise ValidationError("Неизвестное действие с серией.")

    now = timezone.now()
    lessons = list(
        Lesson.objects.select_for_update().filter(
            series=series,
            status=Lesson.Status.SCHEDULED,
            scheduled_start__gte=now,
        )
    )
    lesson_ids = [lesson.id for lesson in lessons]
    if lesson_ids:
        LessonRescheduleRequest.objects.filter(
            lesson_id__in=lesson_ids,
            status=LessonRescheduleRequest.Status.PENDING,
        ).update(
            status=LessonRescheduleRequest.Status.CANCELLED,
            resolved_by=actor,
            resolved_at=now,
        )
    for lesson in lessons:
        lesson.status = Lesson.Status.CANCELLED
        lesson.cancelled_at = now
        lesson.cancellation_reason = "Серия завершена"
        lesson.save(
            update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"]
        )
        _record_event(lesson, LessonEvent.Type.CANCELLED, actor, reason="Серия завершена")
    series.status = LessonSeries.Status.ENDED
    series.end_date = timezone.now().astimezone(series.tzinfo).date()
    if series.end_date < series.start_date:
        series.end_date = series.start_date
    series.save(update_fields=["status", "end_date", "updated_at"])
    return series, len(lessons)


def _series_target_date(series: LessonSeries, through_date: date | None) -> date:
    if through_date is None:
        local_today = timezone.now().astimezone(series.tzinfo).date()
        horizon_start = max(local_today, series.start_date)
        through_date = horizon_start + timedelta(weeks=series.generation_horizon_weeks)
    if series.end_date:
        through_date = min(through_date, series.end_date)
    return through_date


def _localize_series_start(series: LessonSeries, lesson_date: date) -> datetime:
    naive_start = datetime.combine(lesson_date, series.local_time)
    local_start = naive_start.replace(tzinfo=series.tzinfo, fold=0)
    round_trip = (
        local_start.astimezone(datetime_timezone.utc)
        .astimezone(series.tzinfo)
        .replace(tzinfo=None)
    )
    if round_trip != naive_start:
        raise ValidationError(
            "Локальное время не существует из-за перехода на летнее время."
        )
    return local_start


@transaction.atomic
def generate_series_occurrences(
    series: LessonSeries,
    *,
    through_date: date | None = None,
) -> GenerationReport:
    # Lock only the series row. ``created_by`` is nullable, so combining
    # select_for_update() with select_related("created_by") makes PostgreSQL
    # attempt to lock the nullable side of a LEFT OUTER JOIN.
    series = LessonSeries.objects.select_for_update().get(pk=series.pk)
    if series.status != LessonSeries.Status.ACTIVE:
        return GenerationReport()
    _assert_active_link(series.teacher_student_link)

    first_date = series.start_date
    if series.generated_through:
        first_date = max(first_date, series.generated_through + timedelta(days=1))
    last_date = _series_target_date(series, through_date)
    report = GenerationReport(generated_from=first_date, generated_through=last_date)
    if first_date > last_date:
        _finish_elapsed_series(series)
        return report

    current = first_date
    utc = datetime_timezone.utc
    while current <= last_date:
        if current.weekday() in series.weekdays:
            try:
                local_start = _localize_series_start(series, current)
            except ValidationError as exc:
                report.conflicts.append(
                    ScheduleConflict(
                        scheduled_start=datetime.combine(
                            current,
                            series.local_time,
                            tzinfo=series.tzinfo,
                        ),
                        message="; ".join(exc.messages),
                    )
                )
                current += timedelta(days=1)
                continue
            scheduled_start = local_start.astimezone(utc)
            existing = Lesson.objects.filter(
                series=series,
                scheduled_start=scheduled_start,
            ).first()
            if existing is None:
                try:
                    lesson = create_lesson(
                        link=series.teacher_student_link,
                        scheduled_start=scheduled_start,
                        duration_minutes=series.duration_minutes,
                        price_amount=series.price_amount,
                        currency=series.currency,
                        created_by=series.created_by,
                        series=series,
                    )
                except (ValidationError, IntegrityError) as exc:
                    report.conflicts.append(
                        ScheduleConflict(
                            scheduled_start=scheduled_start,
                            message="; ".join(exc.messages)
                            if isinstance(exc, ValidationError)
                            else str(exc),
                        )
                    )
                else:
                    report.created.append(lesson)
        current += timedelta(days=1)

    series.generated_through = last_date
    series.save(update_fields=["generated_through", "updated_at"])
    _finish_elapsed_series(series)
    return report


def _finish_elapsed_series(series: LessonSeries) -> None:
    # Filling the generation horizon does not mean that lessons have finished.
    # A rescheduled occurrence may also extend beyond the recurrence end date.
    if not series.end_date or timezone.now().astimezone(series.tzinfo).date() <= series.end_date:
        return
    if not series.generated_through or series.generated_through < series.end_date:
        return
    now = timezone.now()
    if any(lesson.scheduled_end > now for lesson in series.lessons.filter(status=Lesson.Status.SCHEDULED)):
        return
    series.status = LessonSeries.Status.ENDED
    series.save(update_fields=["status", "updated_at"])


@transaction.atomic
def request_reschedule(
    *,
    lesson: Lesson,
    requested_by,
    proposed_start: datetime,
    reason: str = "",
) -> LessonRescheduleRequest:
    lesson = Lesson.objects.select_for_update().select_related("teacher_student_link").get(pk=lesson.pk)
    _assert_participant(lesson, requested_by)
    if lesson.status != Lesson.Status.SCHEDULED:
        raise ValidationError("Перенести можно только запланированный урок.")
    if LessonRescheduleRequest.objects.filter(
        lesson=lesson,
        status=LessonRescheduleRequest.Status.PENDING,
    ).exists():
        raise ValidationError("Для урока уже существует запрос переноса.")
    conflicts = find_schedule_conflicts(
        link=lesson.teacher_student_link,
        scheduled_start=proposed_start,
        duration_minutes=lesson.duration_minutes,
        exclude_lesson_id=lesson.id,
    )
    if conflicts:
        raise ValidationError("Предлагаемое время пересекается с другим уроком.")
    change_request = LessonRescheduleRequest.objects.create(
        lesson=lesson,
        requested_by=requested_by,
        original_start=lesson.scheduled_start,
        proposed_start=proposed_start,
        reason=reason,
    )
    _record_event(
        lesson,
        LessonEvent.Type.RESCHEDULE_REQUESTED,
        requested_by,
        original_start=lesson.scheduled_start.isoformat(),
        proposed_start=proposed_start.isoformat(),
        reason=reason,
    )
    return change_request


@transaction.atomic
def resolve_reschedule(*, change_request: LessonRescheduleRequest, resolved_by, accept: bool):
    # Match the lesson -> request lock order used when closing a lesson.
    lesson_id = LessonRescheduleRequest.objects.values_list("lesson_id", flat=True).get(
        pk=change_request.pk
    )
    lesson = Lesson.objects.select_for_update().select_related("teacher_student_link").get(
        pk=lesson_id
    )
    _assert_participant(lesson, resolved_by)
    change_request = (
        LessonRescheduleRequest.objects.select_for_update()
        .get(pk=change_request.pk)
    )
    if change_request.status != LessonRescheduleRequest.Status.PENDING:
        raise ValidationError("Запрос переноса уже обработан.")
    if accept and lesson.status != Lesson.Status.SCHEDULED:
        raise ValidationError("Перенести можно только запланированный урок.")
    if accept and lesson.scheduled_start != change_request.original_start:
        raise ValidationError("Время урока уже изменилось. Запрос переноса устарел.")
    if not resolved_by.is_staff and resolved_by.id == change_request.requested_by_id:
        raise PermissionDenied("Инициатор не может подтвердить собственный перенос.")

    now = timezone.now()
    if accept:
        _lock_participants(lesson.teacher_student_link)
        conflicts = find_schedule_conflicts(
            link=lesson.teacher_student_link,
            scheduled_start=change_request.proposed_start,
            duration_minutes=lesson.duration_minutes,
            exclude_lesson_id=lesson.id,
        )
        if conflicts:
            raise ValidationError("Предлагаемое время стало занято другим уроком.")
        old_start = lesson.scheduled_start
        lesson.scheduled_start = change_request.proposed_start
        lesson.save(update_fields=["scheduled_start", "updated_at"])
        change_request.status = LessonRescheduleRequest.Status.ACCEPTED
        event_type = LessonEvent.Type.RESCHEDULE_ACCEPTED
        payload = {
            "original_start": old_start.isoformat(),
            "scheduled_start": lesson.scheduled_start.isoformat(),
        }
    else:
        change_request.status = LessonRescheduleRequest.Status.REJECTED
        event_type = LessonEvent.Type.RESCHEDULE_REJECTED
        payload = {"proposed_start": change_request.proposed_start.isoformat()}

    change_request.resolved_by = resolved_by
    change_request.resolved_at = now
    change_request.save(update_fields=["status", "resolved_by", "resolved_at", "updated_at"])
    _record_event(lesson, event_type, resolved_by, **payload)
    return change_request


@transaction.atomic
def complete_lesson(*, lesson: Lesson, actor, notes: str = "") -> Lesson:
    lesson = Lesson.objects.select_for_update().select_related("teacher_student_link").get(pk=lesson.pk)
    _assert_teacher(lesson, actor)
    if lesson.status == Lesson.Status.COMPLETED:
        return lesson
    if lesson.status != Lesson.Status.SCHEDULED:
        raise ValidationError("Провести можно только запланированный урок.")
    lesson.status = Lesson.Status.COMPLETED
    lesson.completed_at = timezone.now()
    if notes:
        lesson.teacher_notes = notes
    lesson.save(update_fields=["status", "completed_at", "teacher_notes", "updated_at"])
    _close_pending_reschedules(lesson, actor)
    _record_event(lesson, LessonEvent.Type.COMPLETED, actor)
    return lesson


@transaction.atomic
def cancel_lesson(*, lesson: Lesson, actor, reason: str = "") -> Lesson:
    lesson = Lesson.objects.select_for_update().select_related("teacher_student_link").get(pk=lesson.pk)
    _assert_teacher(lesson, actor)
    if lesson.status != Lesson.Status.SCHEDULED:
        raise ValidationError("Отменить можно только запланированный урок.")
    lesson.status = Lesson.Status.CANCELLED
    lesson.cancelled_at = timezone.now()
    lesson.cancellation_reason = reason
    lesson.save(
        update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"]
    )
    _close_pending_reschedules(lesson, actor)
    _record_event(lesson, LessonEvent.Type.CANCELLED, actor, reason=reason)
    return lesson


@transaction.atomic
def mark_no_show(*, lesson: Lesson, actor) -> Lesson:
    lesson = Lesson.objects.select_for_update().select_related("teacher_student_link").get(pk=lesson.pk)
    _assert_teacher(lesson, actor)
    if lesson.status != Lesson.Status.SCHEDULED:
        raise ValidationError("Неявку можно отметить только для запланированного урока.")
    lesson.status = Lesson.Status.NO_SHOW
    lesson.completed_at = timezone.now()
    lesson.save(update_fields=["status", "completed_at", "updated_at"])
    _close_pending_reschedules(lesson, actor)
    _record_event(lesson, LessonEvent.Type.NO_SHOW, actor)
    return lesson


@transaction.atomic
def record_payment(
    *,
    lesson: Lesson,
    actor,
    amount: Decimal | None = None,
    method: str = LessonPayment.Method.BANK_TRANSFER,
    external_id: str = "",
    note: str = "",
) -> LessonPayment:
    lesson = Lesson.objects.select_for_update(of=("self",)).select_related("teacher_student_link").get(pk=lesson.pk)
    _assert_teacher(lesson, actor)
    if lesson.status == Lesson.Status.DELETED:
        raise ValidationError("Нельзя отметить оплату удалённого урока.")
    payment = LessonPayment.objects.select_for_update().get(lesson=lesson)
    if payment.status == LessonPayment.Status.PAID:
        return payment
    payment.amount = amount if amount is not None else lesson.price_amount
    payment.currency = lesson.currency
    payment.status = LessonPayment.Status.PAID
    payment.method = method
    payment.paid_at = timezone.now()
    payment.external_id = external_id
    payment.note = note
    payment.recorded_by = actor
    payment.full_clean()
    payment.save()
    _record_event(
        lesson,
        LessonEvent.Type.PAYMENT_PAID,
        actor,
        amount=str(payment.amount),
        currency=payment.currency,
        method=payment.method,
    )
    return payment


@transaction.atomic
def refund_payment(*, lesson: Lesson, actor, note: str = "") -> LessonPayment:
    lesson = Lesson.objects.select_related("teacher_student_link").get(pk=lesson.pk)
    _assert_teacher(lesson, actor)
    payment = LessonPayment.objects.select_for_update().get(lesson=lesson)
    if payment.status != LessonPayment.Status.PAID:
        raise ValidationError("Вернуть можно только полученную оплату.")
    payment.status = LessonPayment.Status.REFUNDED
    payment.note = note or payment.note
    payment.recorded_by = actor
    payment.save(update_fields=["status", "note", "recorded_by", "updated_at"])
    _record_event(
        lesson,
        LessonEvent.Type.PAYMENT_REFUNDED,
        actor,
        amount=str(payment.amount),
        currency=payment.currency,
    )
    return payment


@transaction.atomic
def reschedule_lesson(*, lesson: Lesson, actor, proposed_start: datetime, reason: str = "") -> Lesson:
    """Teacher moves the existing lesson; its price and payment stay attached."""
    lesson = Lesson.objects.select_for_update(of=("self",)).select_related("teacher_student_link").get(pk=lesson.pk)
    _assert_teacher(lesson, actor)
    if lesson.status != Lesson.Status.SCHEDULED:
        raise ValidationError("Перенести можно только запланированный урок.")
    _lock_participants(lesson.teacher_student_link)
    if find_schedule_conflicts(
        link=lesson.teacher_student_link, scheduled_start=proposed_start,
        duration_minutes=lesson.duration_minutes, exclude_lesson_id=lesson.pk,
    ):
        raise ValidationError("Время пересекается с другим уроком учителя или ученика.")
    original = lesson.scheduled_start
    lesson.scheduled_start = proposed_start
    lesson.full_clean()
    lesson.save(update_fields=["scheduled_start", "updated_at"])
    _close_pending_reschedules(lesson, actor)
    _record_event(lesson, LessonEvent.Type.RESCHEDULED, actor,
                  original_start=original.isoformat(), scheduled_start=proposed_start.isoformat(), reason=reason)
    return lesson


@transaction.atomic
def reopen_lesson(*, lesson: Lesson, actor) -> Lesson:
    """Correct a manual status without changing the payment."""
    lesson = Lesson.objects.select_for_update(of=("self",)).select_related("teacher_student_link").get(pk=lesson.pk)
    _assert_teacher(lesson, actor)
    if lesson.status == Lesson.Status.DELETED:
        raise ValidationError("Удалённый ошибочный урок нельзя вернуть в расписание этой кнопкой.")
    if lesson.status == Lesson.Status.SCHEDULED:
        return lesson
    _lock_participants(lesson.teacher_student_link)
    if find_schedule_conflicts(
        link=lesson.teacher_student_link, scheduled_start=lesson.scheduled_start,
        duration_minutes=lesson.duration_minutes, exclude_lesson_id=lesson.pk,
    ):
        raise ValidationError("Нельзя восстановить урок: это время занято другим занятием.")
    previous_status = lesson.status
    lesson.status = Lesson.Status.SCHEDULED
    lesson.completed_at = None
    lesson.cancelled_at = None
    lesson.cancellation_reason = ""
    lesson.save(update_fields=["status", "completed_at", "cancelled_at", "cancellation_reason", "updated_at"])
    _record_event(lesson, LessonEvent.Type.REOPENED, actor, previous_status=previous_status)
    return lesson


@transaction.atomic
def unmark_payment(*, lesson: Lesson, actor) -> LessonPayment:
    """Correct a mistaken manual mark; this does not perform a refund."""
    lesson = Lesson.objects.select_related("teacher_student_link").get(pk=lesson.pk)
    _assert_teacher(lesson, actor)
    payment = LessonPayment.objects.select_for_update().get(lesson=lesson)
    if payment.status == LessonPayment.Status.UNPAID:
        return payment
    if payment.status != LessonPayment.Status.PAID:
        raise ValidationError("Снять можно только отметку полученной оплаты.")
    _record_event(lesson, LessonEvent.Type.PAYMENT_UNPAID, actor,
                  amount=str(payment.amount), currency=payment.currency,
                  paid_at=payment.paid_at.isoformat() if payment.paid_at else None,
                  method=payment.method, external_id=payment.external_id)
    payment.status = LessonPayment.Status.UNPAID
    payment.paid_at = None
    payment.method = ""
    payment.external_id = ""
    payment.recorded_by = actor
    payment.save(update_fields=["status", "paid_at", "method", "external_id", "recorded_by", "updated_at"])
    return payment


@transaction.atomic
def delete_lesson(*, lesson: Lesson, actor) -> Lesson:
    """Hide an erroneous occurrence; keep the row, series slot and audit history."""
    lesson = Lesson.objects.select_for_update(of=("self",)).select_related("teacher_student_link").get(pk=lesson.pk)
    _assert_teacher(lesson, actor)
    if lesson.status == Lesson.Status.DELETED:
        return lesson
    payment = LessonPayment.objects.select_for_update().get(lesson=lesson)
    if lesson.status != Lesson.Status.SCHEDULED or payment.status != LessonPayment.Status.UNPAID:
        raise ValidationError("Удалить можно только запланированный неоплаченный урок.")
    lesson.status = Lesson.Status.DELETED
    lesson.save(update_fields=["status", "updated_at"])
    _close_pending_reschedules(lesson, actor)
    _record_event(lesson, LessonEvent.Type.DELETED, actor, reason="Урок создан по ошибке")
    return lesson
