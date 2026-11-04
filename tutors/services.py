from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.utils import timezone
from accounts.models import TeacherStudentLink
from lessons.models import Lesson
from students.models import StudentRecord
from .models import Tutor, Offering, Booking


def expire_bookings():
    return Booking.objects.filter(status=Booking.Status.PENDING, expires_at__lte=timezone.now()).update(status=Booking.Status.EXPIRED)


def lock_teacher(tutor):
    # Same lock as lessons.services: all writers serialize on the teacher's User.
    get_user_model().objects.select_for_update().get(pk=tutor.profile.user_id)


def free_slots(offering, *, now=None):
    tutor = offering.tutor
    if not (offering.active and tutor.profile.user.is_active and tutor.status == Tutor.Status.PUBLISHED and tutor.accepting_students and tutor.booking_enabled):
        return []
    now = now or timezone.now()
    tz = ZoneInfo(tutor.timezone)
    first = now.astimezone(tz).date()
    cutoff = now + timedelta(hours=tutor.notice_hours)
    horizon = now + timedelta(days=tutor.horizon_days)
    rules = list(tutor.availability_rules.all())
    exceptions = list(tutor.availability_exceptions.filter(date__gte=first, date__lte=horizon.astimezone(tz).date()))
    busy = [(lesson.scheduled_start, lesson.scheduled_end) for lesson in Lesson.objects.filter(teacher_student_link__teacher_id=tutor.profile.user_id, status=Lesson.Status.SCHEDULED, scheduled_start__gte=now-timedelta(days=46), scheduled_start__lt=horizon)]
    busy += list(Booking.objects.filter(tutor=tutor, status=Booking.Status.PENDING, expires_at__gt=now, end__gt=now, start__lt=horizon).values_list('start', 'end'))
    gap = timedelta(minutes=tutor.break_minutes)
    duration = timedelta(minutes=offering.duration_minutes)
    result = set()
    for offset in range(tutor.horizon_days + 1):
        day = first + timedelta(days=offset)
        overrides = [item for item in exceptions if item.date == day]
        if overrides:
            windows = [] if any(item.closed for item in overrides) else [(item.start_time, item.end_time) for item in overrides]
        else:
            windows = [(item.start_time, item.end_time) for item in rules if item.weekday == day.weekday()]
        for start_time, end_time in windows:
            if not start_time or not end_time:
                continue
            local = datetime.combine(day, start_time)
            local_end = datetime.combine(day, end_time)
            while local + duration <= local_end:
                aware = local.replace(tzinfo=tz)
                start = aware.astimezone(dt_timezone.utc)
                end = start + duration
                # Reject nonexistent DST times and intervals crossing a clock change.
                valid_time = start.astimezone(tz).replace(tzinfo=None) == local and end.astimezone(tz).replace(tzinfo=None) == local + duration
                if valid_time and cutoff <= start <= horizon and not any(a < end + gap and b + gap > start for a, b in busy):
                    result.add(start)
                local += duration + gap
    return sorted(result)


@transaction.atomic
def reserve(*, offering, start, student_name, contact_name, contact_info, visitor_timezone):
    lock_teacher(offering.tutor)
    offering = Offering.objects.select_related('tutor__profile').get(pk=offering.pk)
    if timezone.is_naive(start) or start not in free_slots(offering):
        raise ValidationError('Это время уже недоступно. Выберите другое окошко.')
    now = timezone.now()
    expiry = min(now + timedelta(hours=offering.tutor.confirmation_hours), start)
    booking = Booking(tutor=offering.tutor, offering=offering, start=start, end=start+timedelta(minutes=offering.duration_minutes), duration_minutes=offering.duration_minutes, price=offering.price, expires_at=expiry, student_name=student_name, contact_name=contact_name, contact_info=contact_info, visitor_timezone=visitor_timezone)
    booking.full_clean()
    booking.save()
    return booking


@transaction.atomic
def resolve(*, booking_id, actor=None, action, token=None):
    preliminary = Booking.objects.select_related('tutor__profile').get(pk=booking_id)
    lock_teacher(preliminary.tutor)
    booking = Booking.objects.select_for_update().select_related('tutor__profile', 'offering').get(pk=booking_id)
    owner = actor and actor.is_authenticated and (actor.is_staff or actor.pk == booking.tutor.profile.user_id)
    if not owner and not (action == 'cancel' and token and str(booking.token) == str(token)):
        raise PermissionDenied
    if action not in {'confirm', 'reject', 'cancel'}:
        raise ValidationError('Неизвестное действие.')
    if booking.status == Booking.Status.PENDING and booking.expires_at <= timezone.now():
        booking.status = Booking.Status.EXPIRED
        booking.save(update_fields=['status'])
        return booking
    if booking.status == Booking.Status.CONFIRMED and action == 'cancel':
        if booking.lesson.scheduled_start <= timezone.now():
            raise ValidationError('Для изменения прошедшего занятия свяжитесь с преподавателем.')
        from lessons.services import cancel_lesson
        # The public cancellation link is authority for this booking only.
        cancel_lesson(lesson=booking.lesson, actor=booking.tutor.profile.user, reason='Отмена записи через каталог')
        booking.status = Booking.Status.CANCELLED
    elif booking.status != Booking.Status.PENDING:
        raise ValidationError('Эта запись уже обработана.')
    elif action != 'confirm':
        booking.status = Booking.Status.CANCELLED if action == 'cancel' else Booking.Status.REJECTED
    else:
        if booking.start <= timezone.now():
            raise ValidationError('Время занятия уже прошло.')
        if booking.price is None:
            raise ValidationError('Согласуйте цену и укажите её в записи через администратора перед подтверждением.')
        # Never merge unverified visitors by name/phone or attach them to accounts.
        student = StudentRecord.objects.create(full_name=booking.student_name, created_by=actor, timezone=booking.visitor_timezone, status=StudentRecord.Status.TRIAL, notes=f'Контакт: {booking.contact_name}\n{booking.contact_info}')
        link = TeacherStudentLink.objects.create(teacher=booking.tutor.profile.user, student_record=student, subject=booking.offering.subject, status=TeacherStudentLink.Status.ACTIVE, default_duration_minutes=booking.duration_minutes, default_price_amount=booking.price, activated_at=timezone.now())
        booking.status = Booking.Status.CONFIRMED
        booking.save(update_fields=['status'])
        from lessons.services import create_lesson
        booking.lesson = create_lesson(link=link, scheduled_start=booking.start, duration_minutes=booking.duration_minutes, price_amount=booking.price, created_by=actor)
    booking.save(update_fields=['status', 'lesson'])
    return booking
