from django import forms
from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Skill,
    TaskTag,
    TaskType,
    Task,
    TaskSkill,
    ExamVersion,
    SkillGroup,
    SkillGroupItem,
    Attempt,
    SkillMastery,
    TypeMastery,
    RecommendationLog,
    VariantTemplate,
    VariantTask,
    VariantAssignment,
    VariantAttempt,
    VariantTaskAttempt,
)
from .service_utils import task_generation


class TaskAdminForm(forms.ModelForm):
    default_payload = forms.JSONField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 6, "cols": 80}),
    )
    correct_answer = forms.JSONField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 6, "cols": 80}),
        help_text=(
            "Структура ответа зависит от типа задания. Например: "
            '{"value": 42} или {"choices": [1, 2, 3]}.'
        ),
    )

    class Meta:
        model = Task
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        generator_choices = [("", "---")] + list(
            task_generation.get_generator_choices()
        )
        if "tags" in self.fields:
            self.fields["tags"].queryset = TaskTag.objects.select_related("subject").order_by(
                "subject__name", "name"
            )
        self.fields["generator_slug"].widget = forms.Select(choices=generator_choices)
        self.fields["generator_slug"].required = False
        self.fields["difficulty_level"].help_text = "Число от 0 до 100"

    def clean_generator_slug(self):
        slug = self.cleaned_data.get("generator_slug") or ""
        if slug and not task_generation.is_generator_registered(slug):
            raise forms.ValidationError("Неизвестный генератор")
        return slug


class TaskSkillInline(admin.TabularInline):
    model = TaskSkill
    extra = 1

@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ("name", "subject")
    list_filter = ("subject",)
    search_fields = ("name", "subject__name")


@admin.register(TaskTag)
class TaskTagAdmin(admin.ModelAdmin):
    list_display = ("name", "subject", "slug")
    list_filter = ("subject",)
    search_fields = ("name", "slug", "subject__name")
    ordering = ("subject__name", "name")


@admin.register(TaskType)
class TaskTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "subject", "exam_version")
    list_filter = ("subject", "exam_version")
    search_fields = ("name", "subject__name", "exam_version__name")
    filter_horizontal = ("required_tags",)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "required_tags":
            kwargs["queryset"] = TaskTag.objects.select_related("subject").order_by(
                "subject__name", "name"
            )
        return super().formfield_for_manytomany(db_field, request, **kwargs)


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    form = TaskAdminForm
    inlines = [TaskSkillInline]
    list_display = (
        "title",
        "type",
        "subject",
        "exam_version",
        "is_dynamic",
        "generator_slug",
        "difficulty_level",
        "rendering_strategy",
    )
    search_fields = ("title", "generator_slug")
    list_filter = (
        "type",
        "subject",
        "exam_version",
        "is_dynamic",
        "rendering_strategy",
    )
    filter_horizontal = ("tags",)
    readonly_fields = ("image_preview", "first_attempt_total", "first_attempt_failed")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "title",
                    "subject",
                    "exam_version",
                    "type",
                    "description",
                    "tags",
                    "rendering_strategy",
                    "difficulty_level",
                    "image",
                    "image_preview",
                    "correct_answer",
                )
            },
        ),
        (
            "Динамическая генерация",
            {
                "fields": ("is_dynamic", "generator_slug", "default_payload"),
                "classes": ("collapse",),
            },
        ),
        (
            "Статистика",
            {
                "fields": ("first_attempt_total", "first_attempt_failed"),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description="Предпросмотр")
    def image_preview(self, obj):
        if obj and obj.image:
            return format_html('<img src="{}" style="max-width: 200px;" />', obj.image.url)
        return "—"


class SkillGroupItemInline(admin.TabularInline):
    model = SkillGroupItem
    extra = 1


@admin.register(SkillGroup)
class SkillGroupAdmin(admin.ModelAdmin):
    inlines = [SkillGroupItemInline]
    list_display = ("title", "exam_version")
    list_filter = ("exam_version",)


class SkillGroupInline(admin.TabularInline):
    model = SkillGroup
    extra = 1


@admin.register(ExamVersion)
class ExamVersionAdmin(admin.ModelAdmin):
    inlines = [SkillGroupInline]
    list_display = ("name", "subject")
    list_filter = ("subject",)


admin.site.register(TaskSkill)


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "task",
        "is_correct",
        "attempts_count",
        "weight",
        "variant_task_attempt",
        "created_at",
    )
    list_filter = ("is_correct", "task__type", "task__subject")
    search_fields = ("user__username", "task__title")
    autocomplete_fields = ("user", "task", "variant_task_attempt")


admin.site.register(SkillMastery)
admin.site.register(TypeMastery)
admin.site.register(RecommendationLog)


class VariantTaskInline(admin.TabularInline):
    model = VariantTask
    extra = 1
    ordering = ("order",)


@admin.register(VariantTemplate)
class VariantTemplateAdmin(admin.ModelAdmin):
    inlines = [VariantTaskInline]
    list_display = ("name", "time_limit", "max_attempts", "created_at")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(VariantTask)
class VariantTaskAdmin(admin.ModelAdmin):
    list_display = ("template", "task", "order", "max_attempts")
    ordering = ("template", "order")
    list_filter = ("template",)


@admin.register(VariantAssignment)
class VariantAssignmentAdmin(admin.ModelAdmin):
    list_display = ("template", "user", "deadline", "started_at", "created_at")
    ordering = ("-created_at",)
    list_filter = ("template", "deadline")
    search_fields = ("user__username", "template__name")


@admin.register(VariantAttempt)
class VariantAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "assignment",
        "attempt_number",
        "started_at",
        "completed_at",
        "time_spent",
    )
    ordering = ("assignment", "attempt_number")
    list_filter = ("assignment__template",)


@admin.register(VariantTaskAttempt)
class VariantTaskAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "variant_attempt",
        "variant_task",
        "attempt_number",
        "is_correct",
    )
    ordering = ("variant_attempt", "variant_task", "attempt_number")
    list_filter = ("variant_attempt__assignment__template", "is_correct")
    search_fields = (
        "variant_attempt__assignment__user__username",
        "variant_task__task__title",
    )
