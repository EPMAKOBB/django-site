from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from django import forms
from django.utils import timezone

from accounts.models import TeacherStudentLink, UserPreferences

from .services import create_lesson, create_series, update_series


WEEKDAY_CHOICES = [
    (0, "Понедельник"),
    (1, "Вторник"),
    (2, "Среда"),
    (3, "Четверг"),
    (4, "Пятница"),
    (5, "Суббота"),
    (6, "Воскресенье"),
]


class LessonLinkSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value and hasattr(value, "instance"):
            link = value.instance
            option["attrs"].update({
                "data-duration": link.default_duration_minutes,
                "data-price": str(link.default_price_amount),
                "data-currency": link.currency,
            })
        return option


class TeacherStudentLinkChoiceField(forms.ModelChoiceField):
    widget = LessonLinkSelect

    def label_from_instance(self, obj):
        return (
            f"{obj.student_display_name} — {obj.subject.name} "
            f"({obj.default_duration_minutes} мин, {obj.default_price_amount} {obj.currency})"
        )


class LessonDefaultsForm(forms.Form):
    def configure_defaults(self):
        for name in ("duration_minutes", "price_amount"):
            self.fields[name].required = False
            self.fields[name].help_text = "Если оставить пустым, используются условия выбранного ученика."

    def clean(self):
        cleaned = super().clean()
        link = cleaned.get("teacher_student_link")
        if link:
            for name, default in (
                ("duration_minutes", link.default_duration_minutes),
                ("price_amount", link.default_price_amount),
            ):
                if name not in self.errors and cleaned.get(name) is None:
                    cleaned[name] = default
        return cleaned

    def clean_timezone(self):
        value = self.cleaned_data["timezone"]
        try:
            ZoneInfo(value)
        except (ValueError, KeyError):
            raise forms.ValidationError("Укажите корректный часовой пояс IANA.")
        return value


class LessonSeriesCreateForm(LessonDefaultsForm):
    teacher_student_link = TeacherStudentLinkChoiceField(
        queryset=TeacherStudentLink.objects.none(),
        label="Ученик и предмет",
    )
    weekdays = forms.TypedMultipleChoiceField(
        choices=WEEKDAY_CHOICES,
        coerce=int,
        widget=forms.CheckboxSelectMultiple,
        label="Дни недели",
    )
    local_time = forms.TimeField(
        label="Время",
        widget=forms.TimeInput(attrs={"type": "time"}),
    )
    timezone = forms.CharField(
        max_length=64,
        label="Часовой пояс расписания",
        widget=forms.TextInput(attrs={"list": "lesson-timezones"}),
    )
    start_date = forms.DateField(
        label="Начало",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    end_date = forms.DateField(
        label="Окончание",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Можно не указывать. При создании расписание заполняется на 12 недель вперёд.",
    )
    duration_minutes = forms.IntegerField(label="Продолжительность, минут", min_value=1)
    price_amount = forms.DecimalField(
        label="Стоимость одного урока",
        min_value=Decimal("0.00"),
        max_digits=10,
        decimal_places=2,
    )

    def __init__(self, *args, teacher, **kwargs):
        super().__init__(*args, **kwargs)
        self.teacher = teacher
        self.fields["teacher_student_link"].queryset = (
            TeacherStudentLink.objects.filter(
                teacher=teacher,
                status=TeacherStudentLink.Status.ACTIVE,
            )
            .select_related("student", "student_record", "student_record__user", "subject")
            .order_by("student_record__full_name", "subject__name")
        )
        preferences = getattr(teacher, "preferences", None)
        self.initial.setdefault("timezone", preferences.timezone if preferences else "Europe/Moscow")
        self.initial.setdefault("start_date", timezone.localdate())
        self.configure_defaults()

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "Дата окончания не может быть раньше начала.")
        return cleaned_data

    def save(self):
        return create_series(
            link=self.cleaned_data["teacher_student_link"],
            weekdays=self.cleaned_data["weekdays"],
            local_time=self.cleaned_data["local_time"],
            timezone_name=self.cleaned_data["timezone"],
            start_date=self.cleaned_data["start_date"],
            end_date=self.cleaned_data.get("end_date"),
            duration_minutes=self.cleaned_data["duration_minutes"],
            price_amount=self.cleaned_data["price_amount"],
            currency=self.cleaned_data["teacher_student_link"].currency,
            created_by=self.teacher,
        )


class LessonSeriesUpdateForm(LessonSeriesCreateForm):
    def __init__(self, *args, teacher, series, **kwargs):
        self.series = series
        super().__init__(*args, teacher=teacher, **kwargs)
        for name in ("duration_minutes", "price_amount"):
            self.fields[name].required = True
            self.fields[name].help_text = ""
        self.initial.update(
            {
                "teacher_student_link": series.teacher_student_link_id,
                "weekdays": series.weekdays,
                "local_time": series.local_time,
                "timezone": series.timezone,
                "start_date": series.start_date,
                "end_date": series.end_date,
                "duration_minutes": series.duration_minutes,
                "price_amount": series.price_amount,
            }
        )

    def save(self):
        return update_series(
            series=self.series,
            link=self.cleaned_data["teacher_student_link"],
            weekdays=self.cleaned_data["weekdays"],
            local_time=self.cleaned_data["local_time"],
            timezone_name=self.cleaned_data["timezone"],
            start_date=self.cleaned_data["start_date"],
            end_date=self.cleaned_data.get("end_date"),
            duration_minutes=self.cleaned_data["duration_minutes"],
            price_amount=self.cleaned_data["price_amount"],
            actor=self.teacher,
        )


class LessonCreateForm(LessonDefaultsForm):
    teacher_student_link = TeacherStudentLinkChoiceField(
        queryset=TeacherStudentLink.objects.none(),
        label="Ученик и предмет",
    )
    lesson_date = forms.DateField(
        label="Дата",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    local_time = forms.TimeField(
        label="Время",
        widget=forms.TimeInput(attrs={"type": "time"}),
    )
    timezone = forms.CharField(
        max_length=64,
        label="Часовой пояс",
        widget=forms.TextInput(attrs={"list": "lesson-timezones"}),
    )
    duration_minutes = forms.IntegerField(label="Продолжительность, минут", min_value=1)
    price_amount = forms.DecimalField(
        label="Стоимость урока",
        min_value=Decimal("0.00"),
        max_digits=10,
        decimal_places=2,
    )

    def __init__(self, *args, teacher, **kwargs):
        super().__init__(*args, **kwargs)
        self.teacher = teacher
        self.fields["teacher_student_link"].queryset = (
            TeacherStudentLink.objects.filter(
                teacher=teacher,
                status=TeacherStudentLink.Status.ACTIVE,
            )
            .select_related("student", "student_record", "student_record__user", "subject")
            .order_by("student_record__full_name", "subject__name")
        )
        preferences = getattr(teacher, "preferences", None)
        self.initial.setdefault("timezone", preferences.timezone if preferences else "Europe/Moscow")
        self.initial.setdefault("lesson_date", timezone.localdate())
        self.configure_defaults()

    def clean(self):
        cleaned_data = super().clean()
        lesson_date = cleaned_data.get("lesson_date")
        local_time = cleaned_data.get("local_time")
        timezone_name = cleaned_data.get("timezone")
        if not all((lesson_date, local_time, timezone_name)):
            return cleaned_data
        try:
            zone = ZoneInfo(timezone_name)
        except (ValueError, KeyError):
            self.add_error("timezone", "Укажите корректный часовой пояс IANA.")
            return cleaned_data
        naive_start = datetime.combine(lesson_date, local_time)
        local_start = naive_start.replace(tzinfo=zone, fold=0)
        round_trip = (
            local_start.astimezone(datetime_timezone.utc)
            .astimezone(zone)
            .replace(tzinfo=None)
        )
        if round_trip != naive_start:
            self.add_error("local_time", "Это время не существует из-за перевода часов.")
            return cleaned_data
        cleaned_data["scheduled_start"] = local_start.astimezone(datetime_timezone.utc)
        return cleaned_data

    def save(self):
        return create_lesson(
            link=self.cleaned_data["teacher_student_link"],
            scheduled_start=self.cleaned_data["scheduled_start"],
            duration_minutes=self.cleaned_data["duration_minutes"],
            price_amount=self.cleaned_data["price_amount"],
            currency=self.cleaned_data["teacher_student_link"].currency,
            created_by=self.teacher,
        )


class RescheduleRequestForm(forms.Form):
    proposed_start = forms.DateTimeField(
        label="Новое время",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local"},
        ),
    )
    reason = forms.CharField(
        label="Причина",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class UserTimezoneForm(forms.ModelForm):
    class Meta:
        model = UserPreferences
        fields = ("city", "timezone")
        labels = {
            "city": "Город",
            "timezone": "Часовой пояс",
        }
        widgets = {
            "timezone": forms.TextInput(attrs={"list": "lesson-timezones"}),
        }

    def save(self, commit=True):
        preferences = super().save(commit=False)
        preferences.timezone_confirmed = True
        if commit:
            preferences.save()
        return preferences
