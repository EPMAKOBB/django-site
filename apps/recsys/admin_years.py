"""Annual-exam admin screens, registered from recsys.admin."""
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse

from .models import ExamVersion, ExamProgressSnapshot, TaskPlacement, TaskTypeTransition
from .service_utils.exam_rollover import create_next_year, publish_exam, archive_exam, validate_rollover


class NextYearForm(forms.Form):
    year = forms.IntegerField(label="Новый год", min_value=2000, max_value=2200)
    exam_kind = forms.ChoiceField(label="Экзамен", choices=[("ege", "ЕГЭ"), ("oge", "ОГЭ")])
    new_revision = forms.BooleanField(label="Создать новую редакцию текущего года", required=False,
                                     help_text="Для исправлений опубликованных требований. При выборе сохраняются текущие год и вид экзамена.")


class FrozenAnnualAdminMixin:
    def _frozen(self, obj):
        from .annual_guards import FROZEN, published_parent
        return bool(obj and type(obj) in FROZEN and published_parent(obj, FROZEN[type(obj)]))

    def get_readonly_fields(self, request, obj=None):
        if self._frozen(obj):
            return [f.name for f in obj._meta.fields if f.name != "id"] + [f.name for f in obj._meta.many_to_many]
        return super().get_readonly_fields(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not self._frozen(obj) and super().has_delete_permission(request, obj)


class FrozenAnnualInlineMixin(FrozenAnnualAdminMixin):
    def _frozen(self, obj):
        return bool(isinstance(obj, ExamVersion) and ExamVersion.objects.filter(pk=obj.pk, published_at__isnull=False).exists()) or super()._frozen(obj)

    def get_readonly_fields(self, request, obj=None):
        if self._frozen(obj):
            return [f.name for f in self.model._meta.fields if f.name != "id"]
        return super().get_readonly_fields(request, obj)

    def has_add_permission(self, request, obj=None):
        return not self._frozen(obj) and super().has_add_permission(request, obj)


class PublicationReviewForm(forms.Form):
    source_document = forms.CharField(label="Документ и редакция требований", max_length=1000,
                                      help_text="Например, ссылка на спецификацию ФИПИ и дата её редакции.")
    requirements_checked = forms.BooleanField(label="Структура, темы и критерии проверены")
    scale_checked = forms.BooleanField(label="Шкала проверена или оставлена отключённой до официального подтверждения")
    make_default = forms.BooleanField(label="Рекомендовать эту версию новым пользователям", required=False)


class PlacementInline(admin.TabularInline):
    model = TaskPlacement
    extra = 0
    autocomplete_fields = ["task_type"]


class TransitionInline(FrozenAnnualInlineMixin, admin.TabularInline):
    model = TaskTypeTransition
    fk_name = "target_exam"
    extra = 0
    autocomplete_fields = ["source_type", "target_type"]


class ExamYearAdminMixin:
    change_form_template = "admin/recsys/examversion/change_form.html"

    def get_urls(self):
        return [path("<int:object_id>/next-year/", self.admin_site.admin_view(self.next_year_view), name="recsys_examversion_next_year"),
                path("<int:object_id>/review-year/", self.admin_site.admin_view(self.review_year_view), name="recsys_examversion_review_year")] + super().get_urls()

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.published_at:
            return [field.name for field in obj._meta.fields if field.name != "id"]
        return ["published_at", "is_default", "publication_info"] + (["status"] if obj and obj.copied_from_id else [])

    def next_year_view(self, request, object_id):
        exam = get_object_or_404(ExamVersion, pk=object_id)
        if not self.has_change_permission(request, exam) or not self.has_add_permission(request):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        form = NextYearForm(request.POST or None, initial={"year": exam.year + 1 if exam.year else None, "exam_kind": exam.exam_kind or "ege"})
        if request.method == "POST" and form.is_valid():
            try:
                target = create_next_year(exam, **form.cleaned_data)
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                self.log_change(request, exam, f"Создан черновик экзамена {target.pk}")
                return redirect("admin:recsys_examversion_change", target.pk)
        return render(request, "admin/recsys/examversion/next_year.html", {**self.admin_site.each_context(request), "title": "Создать следующий год", "exam": exam, "form": form})

    def review_year_view(self, request, object_id):
        exam = get_object_or_404(ExamVersion, pk=object_id)
        if not self.has_change_permission(request, exam):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        form = PublicationReviewForm(request.POST or None, initial=exam.publication_info)
        report = validate_rollover(exam)
        if request.method == "POST":
            try:
                if request.POST.get("action") == "archive":
                    archive_exam(exam)
                elif request.POST.get("action") == "publish" and form.is_valid():
                    exam.publication_info = {key: value for key, value in form.cleaned_data.items() if key != "make_default"}
                    exam.save(update_fields=["publication_info", "updated_at"])
                    publish_exam(exam, make_default=form.cleaned_data["make_default"])
                else:
                    raise ValidationError("Заполните подтверждение методической проверки.")
            except ValidationError as exc:
                report["errors"] = exc.messages
            else:
                self.log_change(request, exam, "Изменена доступность годовой версии")
                messages.success(request, "Версия экзамена обновлена.")
                return redirect("admin:recsys_examversion_change", exam.pk)
        return render(request, "admin/recsys/examversion/review_year.html", {**self.admin_site.each_context(request), "title": "Проверка экзамена", "exam": exam, "report": report, "form": form})


@admin.register(TaskPlacement)
class TaskPlacementAdmin(admin.ModelAdmin):
    list_display = ["task", "task_type", "status", "max_score"]
    list_filter = ["task_type__exam_version", "status"]
    search_fields = ["task__title", "task_type__name"]
    autocomplete_fields = ["task", "task_type"]


@admin.register(TaskTypeTransition)
class TaskTypeTransitionAdmin(FrozenAnnualAdminMixin, admin.ModelAdmin):
    list_display = ["source_type", "target_type", "target_exam", "relation", "approved"]
    list_filter = ["target_exam", "relation", "approved"]
    autocomplete_fields = ["source_type", "target_type", "target_exam"]
    actions = ["confirm_equivalent"]

    @admin.action(description="Подтвердить выбранные неизменные соответствия")
    def confirm_equivalent(self, request, queryset):
        count = 0
        for row in queryset.select_related("source_type", "target_type", "target_exam"):
            if row.target_exam.published_at or row.relation != "equivalent":
                continue
            source, target = row.source_type, row.target_type
            if source is None or target is None:
                continue
            if set(source.required_tags.values_list("pk", flat=True)) != set(target.required_tags.values_list("pk", flat=True)):
                continue
            if (source.scoring_scheme, source.max_score, source.answer_schema_id) != (target.scoring_scheme, target.max_score, target.answer_schema_id):
                continue
            row.approved = True
            row.save()
            self.log_change(request, row, "Подтверждено неизменное соответствие")
            count += 1
        self.message_user(request, f"Подтверждено соответствий: {count}. Изменённые требования нужно проверить отдельно.")


@admin.register(ExamProgressSnapshot)
class ExamProgressSnapshotAdmin(admin.ModelAdmin):
    list_display = ["user", "exam_version", "as_of", "purpose", "algorithm_version"]
    list_filter = ["exam_version", "purpose"]
    readonly_fields = [f.name for f in ExamProgressSnapshot._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
