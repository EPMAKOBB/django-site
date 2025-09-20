from django import forms
from django.contrib import admin

from .models import (
    Skill,
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

    class Meta:
        model = Task
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        generator_choices = [("", "---")] + list(
            task_generation.get_generator_choices()
        )
        self.fields["generator_slug"].widget = forms.Select(choices=generator_choices)
        self.fields["generator_slug"].required = False

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


@admin.register(TaskType)
class TaskTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "subject")
    list_filter = ("subject",)


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
                    "rendering_strategy",
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
    )


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
