from django import forms
from django.contrib import admin, messages

from .models import (
    Lesson,
    LessonEvent,
    LessonPayment,
    LessonRescheduleRequest,
    LessonSeries,
)
from .services import generate_series_occurrences
from .services import find_schedule_conflicts


WEEKDAY_CHOICES = [
    (0, "Понедельник"),
    (1, "Вторник"),
    (2, "Среда"),
    (3, "Четверг"),
    (4, "Пятница"),
    (5, "Суббота"),
    (6, "Воскресенье"),
]


class LessonSeriesAdminForm(forms.ModelForm):
    weekdays = forms.TypedMultipleChoiceField(
        choices=WEEKDAY_CHOICES,
        coerce=int,
        widget=forms.CheckboxSelectMultiple,
        label="Дни недели",
    )

    class Meta:
        model = LessonSeries
        fields = "__all__"


class LessonAdminForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        link = cleaned_data.get("teacher_student_link")
        scheduled_start = cleaned_data.get("scheduled_start")
        duration_minutes = cleaned_data.get("duration_minutes")
        status = cleaned_data.get("status")
        if (
            link
            and scheduled_start
            and duration_minutes
            and status == Lesson.Status.SCHEDULED
        ):
            conflicts = find_schedule_conflicts(
                link=link,
                scheduled_start=scheduled_start,
                duration_minutes=duration_minutes,
                exclude_lesson_id=self.instance.pk,
            )
            if conflicts:
                raise forms.ValidationError(
                    "Время пересекается с другим уроком учителя или ученика."
                )
        return cleaned_data


class LessonPaymentInline(admin.StackedInline):
    model = LessonPayment
    extra = 0
    max_num = 1


class LessonRescheduleInline(admin.TabularInline):
    model = LessonRescheduleRequest
    extra = 0
    readonly_fields = ("created_at", "updated_at")


class LessonEventInline(admin.TabularInline):
    model = LessonEvent
    extra = 0
    can_delete = False
    readonly_fields = ("event_type", "actor", "payload", "created_at")
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(LessonSeries)
class LessonSeriesAdmin(admin.ModelAdmin):
    form = LessonSeriesAdminForm
    list_display = (
        "id",
        "teacher_student_link",
        "weekdays",
        "local_time",
        "timezone",
        "price_amount",
        "status",
        "generated_through",
    )
    list_filter = ("status", "timezone", "currency")
    search_fields = (
        "teacher_student_link__teacher__username",
        "teacher_student_link__student__username",
        "teacher_student_link__student_record__full_name",
    )
    autocomplete_fields = ("teacher_student_link", "created_by")
    actions = ("generate_schedule",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        report = generate_series_occurrences(obj)
        if report.created_count or report.conflicts:
            self.message_user(
                request,
                f"Создано уроков: {report.created_count}; конфликтов: {len(report.conflicts)}",
                level=messages.WARNING if report.conflicts else messages.SUCCESS,
            )

    @admin.action(description="Заполнить расписание вперед")
    def generate_schedule(self, request, queryset):
        created = 0
        conflicts = 0
        for series in queryset:
            report = generate_series_occurrences(series)
            created += report.created_count
            conflicts += len(report.conflicts)
        self.message_user(
            request,
            f"Создано уроков: {created}; конфликтов: {conflicts}",
            level=messages.WARNING if conflicts else messages.SUCCESS,
        )


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    form = LessonAdminForm
    list_display = (
        "id",
        "scheduled_start",
        "teacher_username",
        "student_username",
        "subject_name",
        "duration_minutes",
        "price_amount",
        "status",
    )
    list_filter = ("status", "currency", "teacher_student_link__subject")
    search_fields = (
        "teacher_student_link__teacher__username",
        "teacher_student_link__student__username",
        "teacher_student_link__student_record__full_name",
        "teacher_student_link__subject__name",
    )
    autocomplete_fields = ("teacher_student_link", "series", "created_by")
    date_hierarchy = "scheduled_start"
    inlines = (LessonPaymentInline, LessonRescheduleInline, LessonEventInline)

    @admin.display(description="Учитель", ordering="teacher_student_link__teacher__username")
    def teacher_username(self, obj):
        return obj.teacher_student_link.teacher.username

    @admin.display(description="Ученик", ordering="teacher_student_link__student_record__full_name")
    def student_username(self, obj):
        return obj.teacher_student_link.student_display_name

    @admin.display(description="Предмет", ordering="teacher_student_link__subject__name")
    def subject_name(self, obj):
        return obj.teacher_student_link.subject.name


@admin.register(LessonRescheduleRequest)
class LessonRescheduleRequestAdmin(admin.ModelAdmin):
    list_display = ("lesson", "requested_by", "proposed_start", "status", "resolved_by")
    list_filter = ("status",)
    autocomplete_fields = ("lesson", "requested_by", "resolved_by")


@admin.register(LessonPayment)
class LessonPaymentAdmin(admin.ModelAdmin):
    list_display = ("lesson", "amount", "currency", "status", "method", "paid_at")
    list_filter = ("status", "method", "currency")
    search_fields = (
        "lesson__teacher_student_link__teacher__username",
        "lesson__teacher_student_link__student__username",
        "lesson__teacher_student_link__student_record__full_name",
        "external_id",
    )
    autocomplete_fields = ("lesson", "recorded_by")


@admin.register(LessonEvent)
class LessonEventAdmin(admin.ModelAdmin):
    list_display = ("lesson", "event_type", "actor", "created_at")
    list_filter = ("event_type",)
    readonly_fields = ("lesson", "event_type", "actor", "payload", "created_at")
    search_fields = (
        "lesson__teacher_student_link__teacher__username",
        "lesson__teacher_student_link__student__username",
        "lesson__teacher_student_link__student_record__full_name",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
