from collections import OrderedDict
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Prefetch
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from subjects.models import Subject
from .models import Tutor, Offering, Booking
from .forms import SlotForm, BookingForm, CalendarSettingsForm, RuleFormSet, ExceptionFormSet
from .services import free_slots, reserve, resolve, expire_bookings, lock_teacher
from .presentation import catalog_summary


def published():
    return Tutor.objects.filter(status=Tutor.Status.PUBLISHED, profile__user__is_active=True).select_related('profile__user').prefetch_related(Prefetch('offerings', queryset=Offering.objects.filter(active=True).select_related('subject'), to_attr='public_offerings'))


def catalog(request):
    directions = Offering.objects.filter(active=True)
    subject = request.GET.get('subject', '')
    goal = request.GET.get('goal', '')
    grade = request.GET.get('grade', '')
    if subject:
        directions = directions.filter(subject__slug=subject)
    if goal:
        directions = directions.filter(goal=goal)
    if grade:
        if grade.isdigit() and 1 <= int(grade) <= 11:
            directions = directions.filter(grade_from__lte=int(grade), grade_to__gte=int(grade))
        else:
            directions = directions.none()
    tutors = published()
    if subject or goal or grade:
        tutors = tutors.filter(offerings__in=directions).distinct()
    page = Paginator(tutors, 12).get_page(request.GET.get('page'))
    for tutor in page:
        tutor.catalog_summary = catalog_summary(tutor.public_offerings)
    query = request.GET.copy()
    query.pop('page', None)
    return render(request, 'tutors/catalog.html', {'page_obj':page, 'subjects':Subject.objects.order_by('name'), 'goals':Offering.Goal.choices, 'grades':range(1,12), 'subject_filter':subject, 'goal_filter':goal, 'grade_filter':grade, 'filter_query':query.urlencode()})


def detail(request, slug):
    return render(request, 'tutors/detail.html', {'tutor':get_object_or_404(published(), slug=slug)})


def photo(request, slug):
    tutor = get_object_or_404(published(), slug=slug)
    if not tutor.photo:
        raise Http404
    try:
        response = FileResponse(tutor.photo.open('rb'), as_attachment=False)
    except (FileNotFoundError, OSError):
        raise Http404
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@never_cache
def calendar(request, slug):
    tutor = get_object_or_404(published(), slug=slug, booking_enabled=True, accepting_students=True)
    choices = [(item.pk, str(item)) for item in tutor.public_offerings]
    if not choices:
        return render(request, 'tutors/calendar.html', {'tutor':tutor, 'groups':{}, 'no_offerings':True})
    data = request.GET.copy()
    data.setdefault('offering', str(choices[0][0]))
    data.setdefault('timezone', getattr(getattr(request.user, 'preferences', None), 'timezone', 'Europe/Moscow'))
    selection = SlotForm(data)
    selection.fields['offering'].choices = choices
    groups = OrderedDict()
    if selection.is_valid():
        offering = get_object_or_404(Offering, pk=selection.cleaned_data['offering'], tutor=tutor, active=True)
        tz = ZoneInfo(selection.cleaned_data['timezone'])
        for start in free_slots(offering):
            local = start.astimezone(tz)
            query = urlencode({'start': start.isoformat(), 'timezone': selection.cleaned_data['timezone']})
            groups.setdefault(local.date(), []).append({'label':local.strftime('%H:%M'), 'url':reverse('tutors:book', args=[tutor.slug, offering.pk])+'?'+query})
    return render(request, 'tutors/calendar.html', {'tutor':tutor, 'selection':selection, 'groups':groups})


@never_cache
def book(request, slug, offering_id):
    tutor = get_object_or_404(published(), slug=slug, booking_enabled=True, accepting_students=True)
    offering = get_object_or_404(Offering, pk=offering_id, tutor=tutor, active=True)
    selection = SlotForm({'offering':offering.pk, 'timezone':request.GET.get('timezone', 'Europe/Moscow')})
    selection.fields['offering'].choices = [(offering.pk, str(offering))]
    if not selection.is_valid():
        return redirect('tutors:calendar', slug=slug)
    visitor_timezone = selection.cleaned_data['timezone']
    form = BookingForm(request.POST or None, initial={'start':request.GET.get('start')})
    if request.method == 'POST' and form.is_valid():
        key = 'tutor-book:' + salted_hmac('tutor-book', request.META.get('REMOTE_ADDR', '')).hexdigest()
        attempts = cache.get(key, 0)
        if attempts >= 10:
            form.add_error(None, 'Слишком много запросов. Попробуйте через час или свяжитесь с преподавателем напрямую.')
        else:
            cache.set(key, attempts+1, 3600)
            try:
                data = {name:form.cleaned_data[name] for name in ['start','student_name','contact_name','contact_info']}
                booking = reserve(offering=offering, visitor_timezone=visitor_timezone, **data)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                return redirect('tutors:booking-status', token=booking.token)
    start_value = form['start'].value()
    from django.utils.dateparse import parse_datetime
    try:
        start = start_value if hasattr(start_value, 'tzinfo') else parse_datetime(str(start_value or ''))
    except ValueError:
        start = None
    local_start = start.astimezone(ZoneInfo(visitor_timezone)) if start and timezone.is_aware(start) else None
    return render(request, 'tutors/book.html', {'tutor':tutor, 'offering':offering, 'form':form, 'local_start':local_start, 'visitor_timezone':visitor_timezone})


@never_cache
def booking_status(request, token):
    booking = get_object_or_404(Booking.objects.select_related('tutor','offering__subject','lesson'), token=token)
    if request.method == 'POST' and request.POST.get('action') == 'cancel':
        try:
            resolve(booking_id=booking.pk, action='cancel', token=token)
        except ValidationError as error:
            messages.error(request, '; '.join(error.messages))
        return redirect('tutors:booking-status', token=token)
    if booking.status == Booking.Status.PENDING and booking.expires_at <= timezone.now():
        Booking.objects.filter(pk=booking.pk, status=Booking.Status.PENDING, expires_at__lte=timezone.now()).update(status=Booking.Status.EXPIRED)
        booking.refresh_from_db()
    actual_start = booking.lesson.scheduled_start if booking.lesson_id else booking.start
    if booking.lesson_id and booking.lesson.status in {'cancelled', 'deleted'}:
        booking.status = Booking.Status.CANCELLED
    response = render(request, 'tutors/booking_status.html', {'booking':booking, 'local_start':actual_start.astimezone(ZoneInfo(booking.visitor_timezone)), 'local_expiry':booking.expires_at.astimezone(ZoneInfo(booking.visitor_timezone))})
    response['Referrer-Policy'] = 'same-origin'
    return response


@login_required
@never_cache
def manage(request):
    tutor = get_object_or_404(Tutor.objects.select_related('profile__user'), profile__user=request.user)
    settings_form = CalendarSettingsForm(request.POST or None, instance=tutor)
    rules = RuleFormSet(request.POST or None, instance=tutor, prefix='rules')
    exceptions = ExceptionFormSet(request.POST or None, instance=tutor, prefix='exceptions')
    if request.method == 'POST' and all([settings_form.is_valid(), rules.is_valid(), exceptions.is_valid()]):
        with transaction.atomic():
            lock_teacher(tutor)
            settings_form.save()
            rules.save()
            exceptions.save()
        messages.success(request, 'Доступное время сохранено.')
        return redirect('tutors:manage')
    expire_bookings()
    return render(request, 'tutors/manage.html', {'tutor':tutor, 'settings_form':settings_form, 'rules':rules, 'exceptions':exceptions, 'bookings':tutor.bookings.select_related('offering__subject').filter(status__in=[Booking.Status.PENDING,Booking.Status.CONFIRMED], end__gt=timezone.now()), 'role':'teacher', 'active_tab':'tutor-calendar'})


@login_required
@require_POST
def booking_action(request, pk):
    booking = get_object_or_404(Booking, pk=pk, tutor__profile__user=request.user)
    try:
        resolve(booking_id=booking.pk, actor=request.user, action=request.POST.get('action'))
    except ValidationError as error:
        messages.error(request, '; '.join(error.messages))
    else:
        messages.success(request, 'Запись обработана.')
    return redirect('tutors:manage')
