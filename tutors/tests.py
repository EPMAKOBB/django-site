from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta, timezone as utc_timezone
from decimal import Decimal
from threading import Barrier
from zoneinfo import ZoneInfo
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import close_old_connections, connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import TeacherProfile, TeacherStudentLink
from lessons.models import Lesson
from lessons.services import create_lesson, reschedule_lesson
from students.models import StudentRecord
from subjects.models import Subject
from .models import Tutor, Offering, AvailabilityRule, AvailabilityException, Booking
from .services import free_slots, reserve, resolve, expire_bookings
from .presentation import catalog_summary


class CatalogSummaryTests(SimpleTestCase):
    def offers(self, prices, durations=None):
        subject = Subject(pk=1, name='Информатика')
        return [Offering(subject=subject, goal=goal, price=price, duration_minutes=duration)
                for goal, price, duration in zip(['ege', 'oge', 'oge'], prices, durations or [60] * len(prices))]

    def test_subjects_and_goals_are_not_repeated(self):
        summary = catalog_summary(self.offers([2000, None, None]))
        self.assertEqual(summary['subjects'], [{'name': 'Информатика', 'goals': 'ЕГЭ, ОГЭ'}])
        self.assertIsNone(summary['price'])
        self.assertEqual(summary['price_note'], '')

    def test_prices_are_only_compared_for_equal_durations(self):
        for prices, durations, expected, starting in [
            ([2000, 2000], [60, 60], 2000, False),
            ([2000, 3000], [60, 60], 2000, True),
            ([2000, 3000], [60, 90], None, False),
            ([None, None], [60, 60], None, False),
        ]:
            with self.subTest(prices=prices, durations=durations):
                summary = catalog_summary(self.offers(prices, durations))
                self.assertEqual(summary['price'], expected)
                self.assertEqual(summary['from_price'], starting)


def fixture():
    teacher = get_user_model().objects.create_user(username='tutor-test', password='test-pass')
    profile = TeacherProfile.objects.create(user=teacher)
    tutor = Tutor.objects.create(profile=profile, display_name='Тестовый преподаватель', slug='test-tutor', summary='Описание', status=Tutor.Status.PUBLISHED, booking_enabled=True, notice_hours=0, break_minutes=15, horizon_days=7)
    subject = Subject.objects.create(name='Тестовый предмет', slug='test-subject')
    offering = Offering.objects.create(tutor=tutor, subject=subject, goal=Offering.Goal.EGE, grade_from=10, grade_to=11, price=Decimal('2000'), duration_minutes=60)
    day = timezone.now().astimezone(ZoneInfo(tutor.timezone)).date() + timedelta(days=2)
    AvailabilityRule.objects.create(tutor=tutor, weekday=day.weekday(), start_time=time(10), end_time=time(14))
    return teacher,tutor,offering,day


def make_reservation(offering, start):
    return reserve(offering=offering, start=start, student_name='Ученик', contact_name='Родитель', contact_info='test@example.invalid', visitor_timezone='Asia/Vladivostok')


@override_settings(ALLOWED_HOSTS=['testserver'])
class TutorTests(TestCase):
    def setUp(self):
        cache.clear()
        self.teacher,self.tutor,self.offering,self.day = fixture()
        self.start = free_slots(self.offering)[0]

    def test_catalog_detail_and_home_link(self):
        response = self.client.get('/tutors/')
        self.assertContains(response, self.tutor.display_name)
        self.assertContains(response, 'Команда Фрактала', count=0)
        self.assertContains(self.client.get(self.tutor.get_absolute_url()), 'Выбрать время')
        self.assertContains(self.client.get('/'), 'href="/tutors/"')

    def test_unpublished_profile_and_inactive_user_not_public(self):
        self.tutor.status = Tutor.Status.DRAFT;self.tutor.save()
        self.assertNotContains(self.client.get('/tutors/'), self.tutor.display_name)
        self.assertEqual(self.client.get(self.tutor.get_absolute_url()).status_code,404)
        self.assertEqual(self.client.get(reverse('tutors:photo',args=[self.tutor.slug])).status_code,404)
        self.tutor.status=Tutor.Status.PUBLISHED;self.tutor.save()
        self.teacher.is_active=False;self.teacher.save()
        self.assertEqual(self.client.get(self.tutor.get_absolute_url()).status_code,404)

    def test_filters_must_match_same_offering(self):
        other = Subject.objects.create(name='Другой', slug='other')
        Offering.objects.create(tutor=self.tutor, subject=other, goal=Offering.Goal.OGE, grade_from=8, grade_to=9)
        self.assertNotContains(self.client.get('/tutors/?subject=test-subject&goal=oge'), self.tutor.display_name)
        self.assertContains(self.client.get('/tutors/?subject=test-subject&goal=ege&grade=11'), self.tutor.display_name)
        self.assertNotContains(self.client.get('/tutors/?grade=9&subject=test-subject'), self.tutor.display_name)
        self.assertEqual(self.client.get('/tutors/?grade=garbage').status_code,200)

    def test_subject_filter_available_without_published_tutors(self):
        subject = Subject.objects.create(name='Физика', slug='physics')
        self.tutor.status = Tutor.Status.DRAFT
        self.tutor.save()
        response = self.client.get('/tutors/')
        self.assertContains(response, '<option value="physics"')
        self.assertIn(subject, response.context['subjects'])
        self.assertEqual(response.context['page_obj'].paginator.count, 0)

    def test_model_validation(self):
        self.offering.grade_to=8
        with self.assertRaises(ValidationError):self.offering.full_clean()
        rule=AvailabilityRule(tutor=self.tutor,weekday=1,start_time=time(15),end_time=time(10))
        with self.assertRaises(ValidationError):rule.full_clean()
        override=AvailabilityException(tutor=self.tutor,date=self.day,closed=False)
        with self.assertRaises(ValidationError):override.full_clean()

    def test_slots_preserve_duration_and_break(self):
        slots=free_slots(self.offering)
        self.assertEqual(len(slots),3)
        self.assertEqual(slots[1]-slots[0],timedelta(minutes=75))
        self.assertEqual(slots[0].astimezone(ZoneInfo('Europe/Moscow')).hour,10)

    def test_exceptions_replace_regular_hours(self):
        AvailabilityException.objects.create(tutor=self.tutor,date=self.day,closed=True)
        self.assertEqual(free_slots(self.offering),[])
        self.tutor.availability_exceptions.all().delete()
        AvailabilityException.objects.create(tutor=self.tutor,date=self.day,closed=False,start_time=time(17),end_time=time(18))
        slots=free_slots(self.offering)
        self.assertEqual(len(slots),1)
        self.assertEqual(slots[0].astimezone(ZoneInfo('Europe/Moscow')).hour,17)

    def test_duplicate_windows_do_not_duplicate_slots(self):
        AvailabilityRule.objects.create(tutor=self.tutor,weekday=self.day.weekday(),start_time=time(10),end_time=time(14))
        self.assertEqual(len(free_slots(self.offering)),3)

    def test_notice_and_closed_intake(self):
        self.tutor.notice_hours=200;self.tutor.save()
        self.assertEqual(free_slots(self.offering),[])
        self.tutor.notice_hours=0;self.tutor.accepting_students=False;self.tutor.save()
        self.assertEqual(free_slots(self.offering),[])
        with self.assertRaises(ValidationError):make_reservation(self.offering,self.start)

    def test_reservation_blocks_second_and_existing_schedule_writer(self):
        booking=make_reservation(self.offering,self.start)
        self.assertNotIn(self.start,free_slots(self.offering))
        with self.assertRaises(ValidationError):make_reservation(self.offering,self.start)
        student=StudentRecord.objects.create(full_name='Другой ученик')
        link=TeacherStudentLink.objects.create(teacher=self.teacher,student_record=student,subject=self.offering.subject,status=TeacherStudentLink.Status.ACTIVE)
        with self.assertRaises(ValidationError):create_lesson(link=link,scheduled_start=self.start,duration_minutes=60,price_amount=Decimal(1000),created_by=self.teacher)
        resolve(booking_id=booking.pk,action='cancel',token=booking.token)
        self.assertIn(self.start,free_slots(self.offering))

    def test_confirm_creates_one_lesson_and_guest_record(self):
        booking=make_reservation(self.offering,self.start)
        confirmed=resolve(booking_id=booking.pk,actor=self.teacher,action='confirm')
        self.assertEqual(confirmed.status,Booking.Status.CONFIRMED)
        self.assertEqual(confirmed.lesson.price_amount,Decimal(2000))
        self.assertIsNone(confirmed.lesson.teacher_student_link.student_record.user_id)
        self.assertNotIn(self.start,free_slots(self.offering))
        with self.assertRaises(ValidationError):resolve(booking_id=booking.pk,actor=self.teacher,action='confirm')
        self.assertEqual(Lesson.objects.count(),1)

    def test_confirm_requires_agreed_price(self):
        self.offering.price=None;self.offering.save()
        booking=make_reservation(self.offering,self.start)
        with self.assertRaises(ValidationError):resolve(booking_id=booking.pk,actor=self.teacher,action='confirm')
        booking.refresh_from_db();self.assertEqual(booking.status,Booking.Status.PENDING)
        self.assertEqual(StudentRecord.objects.count(),0)

    def test_cancel_confirmed_cancels_lesson(self):
        booking=make_reservation(self.offering,self.start)
        confirmed=resolve(booking_id=booking.pk,actor=self.teacher,action='confirm')
        resolve(booking_id=booking.pk,action='cancel',token=booking.token)
        confirmed.lesson.refresh_from_db()
        self.assertEqual(confirmed.lesson.status,Lesson.Status.CANCELLED)
        self.assertIn(self.start,free_slots(self.offering))

    def test_expired_reservation_is_not_busy(self):
        booking=make_reservation(self.offering,self.start)
        Booking.objects.filter(pk=booking.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertIn(self.start,free_slots(self.offering))
        self.assertEqual(expire_bookings(),1)
        booking.refresh_from_db();self.assertEqual(booking.status,Booking.Status.EXPIRED)

    def test_reject_releases_slot(self):
        booking=make_reservation(self.offering,self.start)
        resolve(booking_id=booking.pk,actor=self.teacher,action='reject')
        self.assertIn(self.start,free_slots(self.offering))

    def test_existing_lessons_and_breaks_remove_slots(self):
        student=StudentRecord.objects.create(full_name='Есть ученик')
        link=TeacherStudentLink.objects.create(teacher=self.teacher,student_record=student,subject=self.offering.subject,status=TeacherStudentLink.Status.ACTIVE)
        create_lesson(link=link,scheduled_start=self.start,duration_minutes=60,price_amount=Decimal(1000),created_by=self.teacher)
        slots=free_slots(self.offering)
        self.assertEqual(len(slots),2)
        self.assertNotIn(self.start,slots)

    def test_other_teacher_cannot_manage_or_confirm(self):
        outsider=get_user_model().objects.create_user(username='outsider',password='test')
        booking=make_reservation(self.offering,self.start)
        with self.assertRaises(PermissionDenied):resolve(booking_id=booking.pk,actor=outsider,action='confirm')
        self.client.force_login(outsider)
        self.assertEqual(self.client.get('/tutors/manage/').status_code,404)
        self.assertEqual(self.client.post(reverse('tutors:booking-action',args=[booking.pk]),{'action':'confirm'}).status_code,404)
        self.assertEqual(self.client.get(reverse('tutors:booking-action',args=[booking.pk])).status_code,405)

    def test_public_booking_and_timezone(self):
        response=self.client.get(reverse('tutors:calendar',args=[self.tutor.slug]),{'timezone':'Asia/Vladivostok'})
        self.assertContains(response,'17:00')
        url=reverse('tutors:book',args=[self.tutor.slug,self.offering.pk])+'?timezone=Asia/Vladivostok'
        response=self.client.post(url,{'start':self.start.isoformat(),'student_name':'Ученик','contact_name':'Родитель','contact_info':'@example','consent':'on'})
        self.assertEqual(response.status_code,302)
        response=self.client.get(response.url)
        self.assertContains(response,'17:00')
        self.assertNotContains(response,'@example')
        self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(self.client.get('/tutors/booking/00000000-0000-0000-0000-000000000000/').status_code,404)

    def test_form_rejects_missing_consent_and_forged_slot(self):
        url=reverse('tutors:book',args=[self.tutor.slug,self.offering.pk])
        data={'start':self.start.isoformat(),'student_name':'Ученик','contact_name':'Родитель','contact_info':'@example'}
        self.client.post(url,data);self.assertEqual(Booking.objects.count(),0)
        data.update(consent='on',start=(self.start+timedelta(minutes=7)).isoformat())
        self.assertContains(self.client.post(url,data),'Это время уже недоступно')
        self.assertEqual(Booking.objects.count(),0)

    def test_owner_calendar_page_and_additional_rows(self):
        self.client.force_login(self.teacher)
        response=self.client.get('/tutors/manage/')
        self.assertContains(response,'Доступное время и записи')
        self.assertContains(response,'rules-TOTAL_FORMS')
        self.assertContains(response,'data-empty')

    def test_timezone_with_plus_sign_is_encoded_in_slot_link(self):
        from urllib.parse import parse_qs, urlparse
        response=self.client.get(reverse('tutors:calendar',args=[self.tutor.slug]),{'timezone':'Etc/GMT+2'})
        groups=response.context['groups']
        link=next(iter(groups.values()))[0]['url']
        self.assertEqual(parse_qs(urlparse(link).query)['timezone'],['Etc/GMT+2'])
        self.assertEqual(self.client.get(link).status_code,200)

    def test_invalid_date_parameter_does_not_crash(self):
        url=reverse('tutors:book',args=[self.tutor.slug,self.offering.pk])
        self.assertEqual(self.client.get(url,{'start':'2027-99-99T99:00:00Z'}).status_code,200)

    def test_public_status_follows_lesson_reschedule(self):
        booking=make_reservation(self.offering,self.start)
        confirmed=resolve(booking_id=booking.pk,actor=self.teacher,action='confirm')
        moved=self.start+timedelta(days=1)
        reschedule_lesson(lesson=confirmed.lesson,actor=self.teacher,proposed_start=moved)
        response=self.client.get(reverse('tutors:booking-status',args=[booking.token]))
        self.assertEqual(response.context['local_start'].astimezone(utc_timezone.utc),moved)

    def test_inactive_teacher_cannot_accept_a_reservation(self):
        self.teacher.is_active=False;self.teacher.save()
        with self.assertRaises(ValidationError):make_reservation(self.offering,self.start)

    def test_dst_nonexistent_slot_is_not_offered(self):
        self.tutor.timezone='Europe/Berlin';self.tutor.horizon_days=2;self.tutor.break_minutes=0;self.tutor.save()
        self.tutor.availability_rules.all().delete()
        AvailabilityException.objects.create(tutor=self.tutor,date=datetime(2027,3,28).date(),closed=False,start_time=time(1),end_time=time(5))
        now=datetime(2027,3,27,0,tzinfo=utc_timezone.utc)
        slots=free_slots(self.offering,now=now)
        hours=[slot.astimezone(ZoneInfo('Europe/Berlin')).hour for slot in slots]
        self.assertNotIn(2,hours)
        self.assertIn(3,hours)


class ReservationConcurrencyTests(TransactionTestCase):
    def test_two_requests_cannot_reserve_same_time(self):
        if connection.vendor != 'postgresql':self.skipTest('Requires PostgreSQL row locks')
        teacher,tutor,offering,day=fixture()
        start=free_slots(offering)[0]
        barrier=Barrier(2)
        def attempt():
            close_old_connections()
            try:
                item=Offering.objects.select_related('tutor__profile').get(pk=offering.pk)
                barrier.wait(timeout=10)
                try:
                    make_reservation(item,start)
                    return 'reserved'
                except ValidationError:
                    return 'busy'
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:attempt(),range(2)))
        self.assertCountEqual(results,['reserved','busy'])
        self.assertEqual(Booking.objects.count(),1)
