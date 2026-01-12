from django import forms
from django.contrib import admin, messages
from django.db import models as django_models
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.html import format_html
from django.utils.text import slugify

from subjects.models import Subject

from .models import (
    Attempt,
    ExamBlueprint,
    ExamBlueprintItem,
    ExamScoreScale,
    ExamVersion,
    RecommendationLog,
    Skill,
    SkillGroup,
    SkillGroupItem,
    SkillMastery,
    Source,
    SourceVariant,
    Task,
    TaskAttachment,
    TaskPreGeneratedDataset,
    TaskSkill,
    TaskTag,
    TaskType,
    TypeMastery,
    VariantAssignment,
    VariantAttempt,
    VariantTask,
    VariantTaskAttempt,
    VariantTemplate,
    VariantPage,
)
from .service_utils import pregenerated_import, task_generation


class TaskPregeneratedUploadForm(forms.Form):
    task = forms.ModelChoiceField(queryset=Task.objects.all(), label="Задание")
    file = forms.FileField(label="Файл с вариантами")
    input_format = forms.ChoiceField(
        label="Формат",
        choices=(("csv", "CSV"), ("json", "JSON")),
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["task"].queryset = Task.objects.order_by("title")


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

    def clean_slug(self):
        value = self.cleaned_data.get("slug") or self.cleaned_data.get("title")
        value = slugify(value or "")
        if not value:
            raise forms.ValidationError("Slug is required.")
        return value

    def clean_generator_slug(self):
        slug = self.cleaned_data.get("generator_slug") or ""
        if slug and not task_generation.is_generator_registered(slug):
            raise forms.ValidationError("Неизвестный генератор")
        return slug


class TaskSkillInline(admin.TabularInline):
    model = TaskSkill
    extra = 1


class TaskPreGeneratedDatasetInline(admin.TabularInline):
    model = TaskPreGeneratedDataset
    extra = 0
    max_num = 0
    can_delete = False
    formfield_overrides = {
        django_models.JSONField: {
            "widget": forms.Textarea(attrs={"rows": 4, "cols": 80}),
        }
    }
    fields = ("parameter_values", "correct_answer", "meta", "is_active")
    readonly_fields = fields
    verbose_name = "Pre-generated dataset"
    verbose_name_plural = "Pre-generated datasets"

    def has_add_permission(self, request, obj=None):
        return False


class TaskAttachmentInline(admin.TabularInline):
    model = TaskAttachment
    extra = 0
    fields = ("kind", "label", "download_name_override", "order", "file")


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
    list_display = ("name", "slug", "subject", "exam_version", "display_order")
    list_filter = ("subject", "exam_version")
    ordering = ("subject__name", "exam_version__name", "display_order", "name")
    list_editable = ("display_order",)
    search_fields = ("name", "slug", "subject__name", "exam_version__name")
    filter_horizontal = ("required_tags",)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "required_tags":
            kwargs["queryset"] = TaskTag.objects.select_related("subject").order_by(
                "subject__name", "name"
            )
        return super().formfield_for_manytomany(db_field, request, **kwargs)


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name", "slug")


@admin.register(SourceVariant)
class SourceVariantAdmin(admin.ModelAdmin):
    list_display = ("label", "source", "slug")
    list_filter = ("source",)
    search_fields = ("label", "slug", "source__name")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    form = TaskAdminForm
    inlines = [TaskSkillInline, TaskAttachmentInline, TaskPreGeneratedDatasetInline]
    change_form_template = "admin/recsys/task/change_form.html"
    list_display = (
        "slug",
        "title",
        "type",
        "subject",
        "source",
        "source_variant",
        "exam_version",
        "is_dynamic",
        "dynamic_mode",
        "generator_slug",
        "difficulty_level",
        "rendering_strategy",
    )
    search_fields = ("title", "slug", "generator_slug")
    list_filter = (
        "type",
        "subject",
        "source",
        "source_variant",
        "exam_version",
        "is_dynamic",
        "dynamic_mode",
        "rendering_strategy",
    )
    filter_horizontal = ("tags",)
    readonly_fields = (
        "image_preview",
        "first_attempt_total",
        "first_attempt_failed",
        "pregenerated_datasets_link",
    )
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "slug",
                    "title",
                    "subject",
                    "exam_version",
                    "type",
                    "source",
                    "source_variant",
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
                "fields": ("is_dynamic", "dynamic_mode", "generator_slug", "default_payload"),
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
        (
            "Предсгенерированные варианты",
            {
                "fields": ("pregenerated_datasets_link",),
            },
        ),
    )

    @admin.display(description="Предпросмотр")
    def image_preview(self, obj):
        if obj and obj.image:
            return format_html('<img src="{}" style="max-width: 200px;" />', obj.image.url)
        return "—"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "pregenerated-upload/",
                self.admin_site.admin_view(self.pregenerated_upload_view),
                name="recsys_task_pregenerated_upload",
            )
        ]
        return custom_urls + urls

    def pregenerated_upload_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied

        next_url = request.GET.get("next") or request.POST.get("next")
        initial: dict = {}
        task_id = request.GET.get("task")
        if task_id:
            initial_task = Task.objects.filter(pk=task_id).first()
            if initial_task:
                initial["task"] = initial_task

        if request.method == "POST":
            form = TaskPregeneratedUploadForm(request.POST, request.FILES)
            if form.is_valid():
                task = form.cleaned_data["task"]
                input_format = form.cleaned_data["input_format"]
                uploaded_file = form.cleaned_data["file"]

                try:
                    result = pregenerated_import.import_pregenerated_datasets(
                        task=task,
                        input_file=uploaded_file,
                        input_format=input_format,
                    )
                except pregenerated_import.DatasetImportError as exc:
                    self.message_user(request, str(exc), level=messages.ERROR)
                else:
                    if result.processed_rows:
                        self.message_user(
                            request,
                            (
                                f"Обработано {result.processed_rows} строк(и); "
                                f"создано {result.created_datasets} вариантов."
                            ),
                            level=messages.SUCCESS,
                        )
                    else:
                        self.message_user(
                            request,
                            "Файл не содержит данных для импорта.",
                            level=messages.WARNING,
                        )

                    for error in result.errors:
                        self.message_user(request, error, level=messages.WARNING)

                return redirect(self._get_redirect_url(request, task, next_url))
        else:
            form = TaskPregeneratedUploadForm(initial=initial)

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "form": form,
            "title": "Импорт предсгенерированных вариантов",
            "next_url": next_url
            or request.GET.get("next")
            or request.META.get("HTTP_REFERER"),
        }
        return render(request, "admin/recsys/task/pregenerated_upload.html", context)

    def _get_redirect_url(self, request, task, next_url):
        if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}
        ):
            return next_url
        if task:
            return reverse("admin:recsys_task_change", args=[task.pk])
        return reverse("admin:recsys_taskpregenerateddataset_changelist")

    @admin.display(description="Варианты")
    def pregenerated_datasets_link(self, obj):
        if not obj or not obj.pk:
            return "—"
        changelist_url = (
            reverse("admin:recsys_taskpregenerateddataset_changelist")
            + f"?task__id__exact={obj.pk}"
        )
        return format_html(
            '<a href="{url}" target="_blank">Список предсгенерированных вариантов</a>',
            url=changelist_url,
        )

@admin.register(TaskPreGeneratedDataset)
class TaskPreGeneratedDatasetAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "task",
        "is_active",
        "short_parameter_values",
        "created_at",
        "updated_at",
    )
    list_filter = ("task", "is_active")
    search_fields = ("parameter_values",)
    list_select_related = ("task",)
    ordering = ("-updated_at",)
    list_per_page = 50

    @admin.display(description="Параметры")
    def short_parameter_values(self, obj):
        data = obj.parameter_values or {}
        text = str(data)
        if len(text) > 120:
            text = text[:117] + "..."
        return text


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
    list_display = ("name", "slug", "status", "subject")
    list_filter = ("subject", "status")
    search_fields = ("name", "slug", "subject__name")


@admin.register(ExamScoreScale)
class ExamScoreScaleAdmin(admin.ModelAdmin):
    list_display = ("exam_version", "max_primary", "is_active", "updated_at")
    list_filter = ("is_active", "exam_version__subject")
    search_fields = ("exam_version__name", "exam_version__subject__name")
    formfield_overrides = {
        django_models.JSONField: {
            "widget": forms.Textarea(attrs={"rows": 6, "cols": 80}),
        }
    }


admin.site.register(TaskSkill)


class ExamBlueprintItemInline(admin.TabularInline):
    model = ExamBlueprintItem
    extra = 1
    ordering = ("order",)
    autocomplete_fields = ("task_type",)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "blueprint",
                "blueprint__subject",
                "blueprint__exam_version",
                "blueprint__exam_version__subject",
                "task_type",
                "task_type__subject",
                "task_type__exam_version",
                "task_type__exam_version__subject",
            )
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "task_type":
            kwargs["queryset"] = TaskType.objects.select_related(
                "exam_version",
                "exam_version__subject",
                "subject",
            ).order_by("subject__name", "exam_version__name", "display_order", "name")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(ExamBlueprint)
class ExamBlueprintAdmin(admin.ModelAdmin):
    inlines = [ExamBlueprintItemInline]
    list_display = ("exam_version", "subject", "is_active", "time_limit", "max_attempts")
    list_filter = ("is_active", "subject")
    search_fields = ("exam_version__name", "subject__name")
    list_select_related = ("exam_version", "subject")

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("exam_version", "exam_version__subject", "subject")
        )

    def get_object(self, request, object_id, from_field=None):
        cache_key = "_cached_exam_blueprint_obj"
        if object_id and hasattr(request, cache_key):
            return getattr(request, cache_key)
        obj = super().get_object(request, object_id, from_field=from_field)
        setattr(request, cache_key, obj)
        return obj

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "exam_version":
            kwargs["queryset"] = ExamVersion.objects.select_related("subject").order_by(
                "subject__name", "name"
            )
        elif db_field.name == "subject":
            kwargs["queryset"] = Subject.objects.order_by("name")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


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


@admin.register(VariantPage)
class VariantPageAdmin(admin.ModelAdmin):
    list_display = ("slug", "template", "is_public", "updated_at")
    list_filter = ("is_public",)
    search_fields = ("slug", "template__name")


class VariantTaskInline(admin.TabularInline):
    model = VariantTask
    extra = 1
    ordering = ("order",)


@admin.register(VariantTemplate)
class VariantTemplateAdmin(admin.ModelAdmin):
    inlines = [VariantTaskInline]
    list_display = (
        "name",
        "exam_version",
        "kind",
        "is_public",
        "display_order",
        "time_limit",
        "max_attempts",
        "created_at",
    )
    search_fields = ("name", "exam_version__name", "slug")
    list_filter = ("exam_version", "kind", "is_public")
    ordering = ("display_order", "name")


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
        "score",
        "max_score",
    )
    ordering = ("variant_attempt", "variant_task", "attempt_number")
    list_filter = ("variant_attempt__assignment__template", "is_correct")
    search_fields = (
        "variant_attempt__assignment__user__username",
        "variant_task__task__title",
    )
