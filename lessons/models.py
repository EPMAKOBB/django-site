from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from accounts.models import (
    DEFAULT_USER_TIMEZONE,
    TeacherStudentLink,
    validate_timezone_name,
)


def validate_weekdays(value) -> None:
    if not isinstance(value, list) or not value:
        raise ValidationError("Выберите хотя бы один день недели.")
    if any(type(day) is not int or day < 0 or day > 6 for day in value):
        raise ValidationError("Дни недели должны быть числами от 0 до 6.")
    if len(value) != len(set(value)):
        raise ValidationError("Дни недели не должны повторяться.")


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class LessonSeries(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Активна"
        PAUSED = "paused", "Приостановлена"
        ENDED = "ended", "Завершена"

    teacher_student_link = models.ForeignKey(
        TeacherStudentLink,
        on_delete=models.PROTECT,
        related_name="lesson_series",
    )
    weekdays = models.JSONField(default=list, validators=[validate_weekdays])
    local_time = models.TimeField()
    timezone = models.CharField(
        max_length=64,
        default=DEFAULT_USER_TIMEZONE,
        validators=[validate_timezone_name],
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    duration_minutes = models.PositiveSmallIntegerField(
        default=60,
        validators=[MinValueValidator(1)],
    )
    price_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    currency = models.CharField(max_length=3, default="RUB")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    generation_horizon_weeks = models.PositiveSmallIntegerField(
        default=12,
        validators=[MinValueValidator(1)],
    )
    generated_through = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="lesson_series_created",
    )

    class Meta:
        ordering = ["start_date", "local_time", "id"]
        indexes = [
            models.Index(fields=["status", "start_date"]),
            models.Index(fields=["teacher_student_link", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(price_amount__gte=0),
                name="lesson_series_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(end_date__isnull=True) | Q(end_date__gte=models.F("start_date")),
                name="lesson_series_dates_valid",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        validate_weekdays(self.weekdays)
        validate_timezone_name(self.timezone)
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "Дата окончания не может быть раньше начала."})
        self.weekdays = sorted(set(self.weekdays))
        self.currency = (self.currency or "RUB").upper()

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def __str__(self) -> str:
        days = ",".join(str(day) for day in self.weekdays)
        return f"{self.teacher_student_link} · [{days}] {self.local_time}"


class Lesson(TimeStampedModel):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Запланирован"
        COMPLETED = "completed", "Проведен"
        CANCELLED = "cancelled", "Отменен"
        NO_SHOW = "no_show", "Неявка"
        DELETED = "deleted", "Удалён как ошибочный"

    teacher_student_link = models.ForeignKey(
        TeacherStudentLink,
        on_delete=models.PROTECT,
        related_name="lessons",
    )
    series = models.ForeignKey(
        LessonSeries,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lessons",
    )
    scheduled_start = models.DateTimeField()
    duration_minutes = models.PositiveSmallIntegerField(
        default=60,
        validators=[MinValueValidator(1)],
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SCHEDULED)
    price_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    currency = models.CharField(max_length=3, default="RUB")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="lessons_created",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    teacher_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["scheduled_start", "id"]
        indexes = [
            models.Index(fields=["scheduled_start", "status"]),
            models.Index(fields=["teacher_student_link", "scheduled_start"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(price_amount__gte=0),
                name="lesson_price_nonnegative",
            ),
            models.UniqueConstraint(
                fields=["series", "scheduled_start"],
                condition=Q(series__isnull=False),
                name="lesson_series_start_unique",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.series_id and self.teacher_student_link_id != self.series.teacher_student_link_id:
            raise ValidationError({"series": "Серия и урок должны относиться к одной связи."})
        self.currency = (self.currency or "RUB").upper()

    @property
    def scheduled_end(self):
        return self.scheduled_start + timedelta(minutes=self.duration_minutes)

    def __str__(self) -> str:
        return f"{self.teacher_student_link} · {self.scheduled_start:%Y-%m-%d %H:%M}"


class LessonRescheduleRequest(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает решения"
        ACCEPTED = "accepted", "Принят"
        REJECTED = "rejected", "Отклонен"
        CANCELLED = "cancelled", "Отозван"

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="reschedule_requests")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="lesson_reschedule_requests",
    )
    original_start = models.DateTimeField()
    proposed_start = models.DateTimeField()
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lesson_reschedule_resolutions",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["lesson", "status"])]
        constraints = [
            models.UniqueConstraint(
                fields=["lesson"],
                condition=Q(status="pending"),
                name="lesson_one_pending_reschedule",
            )
        ]

    def __str__(self) -> str:
        return f"{self.lesson} → {self.proposed_start:%Y-%m-%d %H:%M}"


class LessonPayment(TimeStampedModel):
    class Status(models.TextChoices):
        UNPAID = "unpaid", "Не оплачен"
        PAID = "paid", "Оплачен"
        REFUNDED = "refunded", "Возвращен"

    class Method(models.TextChoices):
        BANK_TRANSFER = "bank_transfer", "Перевод"
        CASH = "cash", "Наличные"
        ONLINE = "online", "Онлайн"
        OTHER = "other", "Другое"

    lesson = models.OneToOneField(Lesson, on_delete=models.PROTECT, related_name="payment")
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    currency = models.CharField(max_length=3, default="RUB")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UNPAID)
    method = models.CharField(max_length=24, choices=Method.choices, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    external_id = models.CharField(max_length=128, blank=True, db_index=True)
    note = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lesson_payments_recorded",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gte=0),
                name="lesson_payment_amount_nonnegative",
            )
        ]

    def clean(self) -> None:
        super().clean()
        self.currency = (self.currency or "RUB").upper()

    def __str__(self) -> str:
        return f"{self.lesson} · {self.amount} {self.currency} ({self.status})"


class LessonEvent(models.Model):
    class Type(models.TextChoices):
        CREATED = "created", "Создан"
        RESCHEDULE_REQUESTED = "reschedule_requested", "Запрошен перенос"
        RESCHEDULE_ACCEPTED = "reschedule_accepted", "Перенос принят"
        RESCHEDULE_REJECTED = "reschedule_rejected", "Перенос отклонен"
        COMPLETED = "completed", "Проведен"
        CANCELLED = "cancelled", "Отменен"
        NO_SHOW = "no_show", "Неявка"
        PAYMENT_PAID = "payment_paid", "Оплата получена"
        PAYMENT_REFUNDED = "payment_refunded", "Оплата возвращена"
        RESCHEDULED = "rescheduled", "Перенесён учителем"
        REOPENED = "reopened", "Отметка проведения отменена"
        PAYMENT_UNPAID = "payment_unpaid", "Отметка оплаты отменена"
        DELETED = "deleted", "Ошибочный урок удалён"

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=32, choices=Type.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lesson_events",
    )
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["lesson", "created_at"])]

    def __str__(self) -> str:
        return f"{self.lesson} · {self.event_type}"
