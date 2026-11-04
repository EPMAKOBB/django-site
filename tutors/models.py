import uuid
from datetime import date
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.urls import reverse
from accounts.models import TeacherProfile, validate_timezone_name
from subjects.models import Subject


class Tutor(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Черновик'
        REVIEW = 'review', 'На проверке'
        PUBLISHED = 'published', 'Опубликована'
        HIDDEN = 'hidden', 'Скрыта'

    class Affiliation(models.TextChoices):
        TEAM = 'team', 'Команда Фрактала'
        INDEPENDENT = 'independent', 'Независимый преподаватель'

    profile = models.OneToOneField(TeacherProfile, on_delete=models.PROTECT, related_name='public_tutor', verbose_name='Рабочий профиль')
    display_name = models.CharField('Имя для сайта', max_length=160)
    slug = models.SlugField('Адрес страницы', unique=True, max_length=180)
    photo = models.ImageField('Фото', upload_to='tutors/%Y/%m/', blank=True)
    summary = models.CharField('Краткое описание', max_length=300)
    description = models.TextField('О преподавателе', blank=True)
    education = models.TextField('Образование', blank=True)
    teaching_since = models.PositiveSmallIntegerField('Год начала преподавания', null=True, blank=True, validators=[MinValueValidator(1950)])
    affiliation = models.CharField('Принадлежность', max_length=16, choices=Affiliation.choices, default=Affiliation.INDEPENDENT)
    status = models.CharField('Публикация', max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    accepting_students = models.BooleanField('Принимает учеников', default=True)
    contacts = models.TextField('Публичные контакты', blank=True, help_text='Telegram, телефон, почта. Только контакты для публикации.')
    sort_order = models.PositiveIntegerField('Порядок в каталоге', default=100)
    timezone = models.CharField('Часовой пояс', max_length=64, default='Europe/Moscow', validators=[validate_timezone_name])
    booking_enabled = models.BooleanField('Включить запись через календарь', default=False)
    break_minutes = models.PositiveSmallIntegerField('Перерыв между занятиями, минут', default=15, validators=[MaxValueValidator(180)])
    notice_hours = models.PositiveSmallIntegerField('До занятия не менее, часов', default=24, validators=[MaxValueValidator(720)])
    horizon_days = models.PositiveSmallIntegerField('Запись вперёд, дней', default=28, validators=[MinValueValidator(1), MaxValueValidator(90)])
    confirmation_hours = models.PositiveSmallIntegerField('Срок подтверждения, часов', default=12, validators=[MinValueValidator(1), MaxValueValidator(72)])

    class Meta:
        ordering = ['sort_order', 'display_name', 'pk']
        verbose_name = 'Анкета репетитора'
        verbose_name_plural = 'Анкеты репетиторов'

    def __str__(self):
        return self.display_name

    def clean(self):
        super().clean()
        if self.slug == 'manage':
            raise ValidationError({'slug': 'Этот адрес занят служебной страницей.'})
        if self.teaching_since and self.teaching_since > date.today().year:
            raise ValidationError({'teaching_since': 'Год не может быть в будущем.'})

    def get_absolute_url(self):
        return reverse('tutors:detail', args=[self.slug])

    @property
    def initials(self):
        return ''.join(part[0] for part in self.display_name.split()[:2])

    @property
    def photo_url(self):
        return reverse('tutors:photo', args=[self.slug]) if self.photo else ''


class Offering(models.Model):
    class Goal(models.TextChoices):
        EGE = 'ege', 'ЕГЭ'
        OGE = 'oge', 'ОГЭ'
        SCHOOL = 'school', 'Школьная программа'
        OLYMPIAD = 'olympiad', 'Олимпиады'

    class Format(models.TextChoices):
        ONLINE = 'online', 'Онлайн'
        OFFLINE = 'offline', 'Очно'
        BOTH = 'both', 'Онлайн и очно'

    tutor = models.ForeignKey(Tutor, on_delete=models.CASCADE, related_name='offerings')
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, verbose_name='Предмет')
    goal = models.CharField('Цель', max_length=16, choices=Goal.choices)
    grade_from = models.PositiveSmallIntegerField('С класса', default=1, validators=[MinValueValidator(1), MaxValueValidator(11)])
    grade_to = models.PositiveSmallIntegerField('По класс', default=11, validators=[MinValueValidator(1), MaxValueValidator(11)])
    price = models.DecimalField('Цена, ₽', max_digits=10, decimal_places=2, blank=True, null=True, validators=[MinValueValidator(0)])
    duration_minutes = models.PositiveSmallIntegerField('Длительность, минут', default=60, validators=[MinValueValidator(15), MaxValueValidator(240)])
    format = models.CharField('Формат', max_length=16, choices=Format.choices, default=Format.ONLINE)
    city = models.CharField('Город очных занятий', max_length=120, blank=True)
    active = models.BooleanField('Активно', default=True)

    class Meta:
        ordering = ['subject__name', 'goal', 'pk']
        verbose_name = 'Направление'
        verbose_name_plural = 'Направления'
        constraints = [models.CheckConstraint(condition=models.Q(grade_to__gte=models.F('grade_from')), name='tutor_offering_grades_valid'), models.CheckConstraint(condition=models.Q(price__isnull=True) | models.Q(price__gte=0), name='tutor_offering_price_valid')]

    def clean(self):
        super().clean()
        if self.grade_from > self.grade_to:
            raise ValidationError({'grade_to': 'Последний класс меньше первого.'})
        if self.format != self.Format.ONLINE and not self.city.strip():
            raise ValidationError({'city': 'Укажите город очных занятий.'})

    def __str__(self):
        return f'{self.subject} · {self.get_goal_display()} · {self.duration_minutes} мин'


class AvailabilityRule(models.Model):
    tutor = models.ForeignKey(Tutor, on_delete=models.CASCADE, related_name='availability_rules')
    weekday = models.PositiveSmallIntegerField('День недели', choices=list(enumerate(['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'])))
    start_time = models.TimeField('С')
    end_time = models.TimeField('До')

    class Meta:
        ordering = ['weekday', 'start_time']
        verbose_name = 'Рабочие часы'
        verbose_name_plural = 'Рабочие часы'
        constraints = [models.CheckConstraint(condition=models.Q(end_time__gt=models.F('start_time')), name='tutor_rule_times_valid'), models.CheckConstraint(condition=models.Q(weekday__lte=6), name='tutor_rule_weekday_valid')]

    def clean(self):
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError('Окончание должно быть позже начала. Ночные часы разделите по дням.')

    def __str__(self):
        return f'{self.get_weekday_display()} {self.start_time:%H:%M}–{self.end_time:%H:%M}'


class AvailabilityException(models.Model):
    tutor = models.ForeignKey(Tutor, on_delete=models.CASCADE, related_name='availability_exceptions')
    date = models.DateField('Дата')
    closed = models.BooleanField('Выходной', default=True, help_text='Все исключения этой даты заменяют обычное расписание.')
    start_time = models.TimeField('С', null=True, blank=True)
    end_time = models.TimeField('До', null=True, blank=True)

    class Meta:
        ordering = ['date', 'start_time']
        verbose_name = 'Исключение расписания'
        verbose_name_plural = 'Исключения расписания'

    def clean(self):
        if not self.closed and (not self.start_time or not self.end_time or self.start_time >= self.end_time):
            raise ValidationError('Для рабочего дня укажите начало и окончание.')


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Ожидает подтверждения'
        CONFIRMED = 'confirmed', 'Подтверждена'
        REJECTED = 'rejected', 'Отклонена'
        CANCELLED = 'cancelled', 'Отменена'
        EXPIRED = 'expired', 'Срок подтверждения истёк'

    tutor = models.ForeignKey(Tutor, on_delete=models.PROTECT, related_name='bookings')
    offering = models.ForeignKey(Offering, on_delete=models.PROTECT, verbose_name='Направление')
    start = models.DateTimeField('Начало')
    end = models.DateTimeField('Окончание')
    duration_minutes = models.PositiveSmallIntegerField()
    price = models.DecimalField('Согласованная цена, ₽', max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    student_name = models.CharField('Имя ученика', max_length=160)
    contact_name = models.CharField('Имя контактного лица', max_length=160)
    contact_info = models.CharField('Как с вами связаться', max_length=255)
    visitor_timezone = models.CharField(max_length=64, validators=[validate_timezone_name])
    status = models.CharField('Статус', max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    expires_at = models.DateTimeField('Подтвердить до')
    created_at = models.DateTimeField(auto_now_add=True)
    lesson = models.OneToOneField('lessons.Lesson', on_delete=models.PROTECT, null=True, blank=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        ordering = ['start', 'pk']
        verbose_name = 'Запись на занятие'
        verbose_name_plural = 'Записи на занятия'
        indexes = [models.Index(fields=['tutor', 'status', 'start'])]
        constraints = [models.CheckConstraint(condition=models.Q(end__gt=models.F('start')), name='tutor_booking_times_valid')]

    @property
    def scheduled_end(self):
        return self.end

    def __str__(self):
        return f'{self.tutor} · {self.start:%d.%m %H:%M}'
