
import json
import logging
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.template.loader import render_to_string
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from rest_framework import exceptions as drf_exceptions

from .models import (
    ExamVersion,
    ExamBlueprint,
    Skill,
    SkillMastery,
    Source,
    SourceVariant,
    Task,
    TaskSkill,
    TaskTag,
    TaskType,
    VariantAssignment,
    VariantPage,
    VariantTemplate,
)
from .recommendation import recommend_tasks
from .forms import TaskUploadForm
from accounts.models import ClassTeacherSubject, StudentProfile, TeacherStudentLink
from apps.recsys.service_utils import variants as variant_services
from apps.recsys.service_utils.type_progress import build_type_progress_map
from subjects.models import Subject


logger = logging.getLogger("recsys")


@login_required
def dashboard(request):
    """Display progress for the current user."""
    masteries = (
        SkillMastery.objects.filter(user=request.user)
        .select_related("skill")
        .order_by("skill__name")
    )
    return render(
        request,
        "recsys/dashboard.html",
        {"skill_masteries": masteries},
    )


@login_required
def teacher_user(request, user_id):
    """Display progress for a specific student."""
    user_model = get_user_model()
    student = get_object_or_404(user_model, pk=user_id)
    if not request.user.is_staff:
        has_link = TeacherStudentLink.objects.filter(
            teacher=request.user,
            student=student,
            status=TeacherStudentLink.Status.ACTIVE,
        ).exists()
        shares_class = ClassTeacherSubject.objects.filter(
            teacher=request.user,
            study_class__student_memberships__student=student,
        ).exists()
        if not (has_link or shares_class):
            raise Http404("Student not accessible.")
    masteries = (
        SkillMastery.objects.filter(user=student)
        .select_related("skill")
        .order_by("skill__name")
    )
    context = {"student": student, "skill_masteries": masteries}
    return render(request, "recsys/teacher_user.html", context)


def _get_exam_by_slug(exam_slug: str) -> ExamVersion:
    exam_qs = ExamVersion.objects.select_related("subject")
    exam = exam_qs.filter(slug=exam_slug).first()
    if exam is None:
        fallback = None
        for candidate in exam_qs:
            if slugify(candidate.name) == exam_slug:
                fallback = candidate
                break
        if fallback is None:
            raise Http404("Exam not found")
        exam = fallback
    return exam


def exam_page(request, exam_slug: str):
    """Public exam landing with personal variant builder."""

    exam = _get_exam_by_slug(exam_slug)

    if request.method == "POST" and request.POST.get("action") == "build_personal":
        if not request.user.is_authenticated:
            return redirect(f"{reverse('accounts:login')}?next={request.path}")
        try:
            assignment = variant_services.build_personal_assignment_from_blueprint(
                user=request.user,
                exam_version=exam,
            )
        except drf_exceptions.ValidationError as exc:
            logger.info("Personal assignment validation error", extra={"exam_id": exam.id}, exc_info=exc)
            messages.error(request, _("Не удалось собрать персональный вариант."))
        else:
            page = variant_services.ensure_variant_page(assignment.template, is_public=False)
            return redirect("variant-page", slug=page.slug)

    context = {
        "exam": exam,
        "exam_slug": exam.slug or exam_slug,
        "is_authenticated": request.user.is_authenticated,
    }
    return render(request, "exams/detail.html", context)


def _get_exam_type_by_slug(exam: ExamVersion, type_slug: str) -> TaskType:
    task_type = (
        TaskType.objects.select_related("subject", "exam_version")
        .filter(exam_version=exam, slug=type_slug)
        .first()
    )
    if task_type is None:
        fallback = None
        for candidate in TaskType.objects.filter(exam_version=exam):
            if slugify(candidate.name) == type_slug:
                fallback = candidate
                break
        if fallback is None:
            raise Http404("Task type not found")
        task_type = fallback
    return task_type


def exam_type_page(request, exam_slug: str, type_slug: str):
    """Public page that lists tasks for a specific exam task type."""
    exam = _get_exam_by_slug(exam_slug)
    task_type = _get_exam_type_by_slug(exam, type_slug)
    tasks = (
        Task.objects.filter(type=task_type)
        .select_related("subject", "exam_version", "type")
        .prefetch_related("skills")
        .order_by("id")
    )
    context = {
        "exam": exam,
        "task_type": task_type,
        "tasks": tasks,
    }
    return render(request, "exams/type_detail.html", context)


def exam_public_blocks(request, exam_slug: str):
    """Return non-personal exam blocks (builder, static variants, types/tags)."""
    exam = _get_exam_by_slug(exam_slug)
    blueprint = (
        ExamBlueprint.objects.filter(exam_version=exam, is_active=True)
        .order_by("-updated_at", "-id")
        .first()
    )
    static_variants = (
        VariantTemplate.objects.filter(
            exam_version=exam,
            is_public=True,
            page__is_public=True,
        )
        .select_related("page")
        .order_by("display_order", "name")
    )
    type_rows = []
    if blueprint:
        items = (
            blueprint.items.select_related("task_type")
            .prefetch_related("task_type__required_tags")
            .order_by("order", "id")
        )
        for item in items:
            task_type = item.task_type
            if not task_type:
                continue
            type_rows.append(
                {
                    "item": item,
                    "type": task_type,
                    "required_tags": tuple(task_type.required_tags.all()),
                }
            )

    html = render_to_string(
        "exams/_public_blocks.html",
        {
            "exam": exam,
            "blueprint": blueprint,
            "static_variants": static_variants,
            "type_rows": type_rows,
            "is_authenticated": request.user.is_authenticated,
        },
        request=request,
    )
    return JsonResponse({"html": html})


def exam_progress_data(request, exam_slug: str):
    """Return progress data per task type/tag for authenticated users."""
    if not request.user.is_authenticated:
        return JsonResponse({"type_progress": {}, "tag_progress": {}})

    exam = _get_exam_by_slug(exam_slug)
    blueprint = (
        ExamBlueprint.objects.filter(exam_version=exam, is_active=True)
        .prefetch_related("items__task_type")
        .order_by("-updated_at", "-id")
        .first()
    )
    if not blueprint:
        return JsonResponse({"type_progress": {}, "tag_progress": {}})

    type_ids = list(
        blueprint.items.values_list("task_type_id", flat=True)
    )
    type_progress_map = build_type_progress_map(
        user=request.user,
        task_type_ids=type_ids,
    )
    type_progress = {}
    tag_progress = {}
    for type_id, info in type_progress_map.items():
        percent = int(round((info.effective_mastery or 0) * 100))
        type_progress[str(type_id)] = {
            "percent": percent,
        }
        tag_progress[str(type_id)] = {
            str(entry.tag.id): int(round(entry.ratio * 100))
            for entry in info.tag_progress
        }

    return JsonResponse(
        {
            "type_progress": type_progress,
            "tag_progress": tag_progress,
        }
    )


def variant_page(request, slug: str):
    """Public page that renders a variant by slug with start button."""

    page_qs = VariantPage.objects.select_related(
        "template",
        "template__exam_version",
        "template__exam_version__subject",
    ).prefetch_related(
        "template__template_tasks__task__subject",
        "template__template_tasks__task__type",
    )
    page = get_object_or_404(page_qs, slug=slug)
    if not page.is_public:
        if not request.user.is_authenticated:
            return redirect(f"{reverse('accounts:login')}?next={request.path}")
        allowed = request.user.is_staff or VariantAssignment.objects.filter(
            template=page.template, user=request.user
        ).exists()
        if not allowed:
            raise Http404("Variant is not available.")

    template = page.template
    template_tasks = list(
        template.template_tasks.select_related("task__subject", "task__type", "task").order_by("order")
    )

    if request.method == "POST" and request.POST.get("action") == "start":
        if not request.user.is_authenticated:
            return redirect(f"{reverse('accounts:login')}?next={request.path}")
        assignment, _ = VariantAssignment.objects.get_or_create(
            template=template,
            user=request.user,
        )
        active_attempt = (
            assignment.attempts.filter(completed_at__isnull=True).order_by("attempt_number").first()
        )
        try:
            attempt = active_attempt or variant_services.start_new_attempt(request.user, assignment.id)
        except drf_exceptions.ValidationError as exc:
            logger.info("Variant start validation error", extra={"template_id": template.id}, exc_info=exc)
            messages.error(request, _("Не удалось начать попытку."))
        except drf_exceptions.APIException as exc:
            logger.warning("Variant start API error", extra={"template_id": template.id}, exc_info=exc)
            messages.error(request, _("Не удалось начать попытку."))
        else:
            return redirect("accounts:variant-attempt-solver", attempt_id=attempt.id)

    tasks = []
    for variant_task in template_tasks:
        task = variant_task.task
        display = {
            "title": getattr(task, "title", "") if task else "",
            "description": getattr(task, "description", "") if task else "",
            "rendering_strategy": getattr(task, "rendering_strategy", None) if task else None,
            "image": task.image.url if getattr(task, "image", None) else None,
        }
        tasks.append(
            {
                "variant_task": variant_task,
                "task": task,
                "order": variant_task.order,
                "display": display,
            }
        )

    tasks.sort(key=lambda entry: entry["order"] or 0)

    context = {
        "page": page,
        "template": template,
        "page_title": page.title or template.name,
        "page_description": page.description or template.description,
        "tasks": tasks,
    }
    return render(request, "variants/detail.html", context)


def tasks_list(request):
    """Public page that lists tasks with filters and sorting.

    Filters:
    - exam versions (preselected from student's profile if available)
    - dynamic/static tasks
    Sorting:
    - new (default), old, hard, easy, personal
    """

    # Build exams list grouped by subject for rendering checkboxes
    subjects = (
        ExamVersion.objects.select_related("subject")
        .order_by("subject__name", "name")
        .values("id", "name", "subject__id", "subject__name")
    )
    # Collate into {subject_id: {"name": ..., "exams": [...]}}
    exams_by_subject: dict[int, dict] = {}
    for ev in subjects:
        sid = ev["subject__id"]
        if sid not in exams_by_subject:
            exams_by_subject[sid] = {
                "subject_id": sid,
                "subject_name": ev["subject__name"],
                "exams": [],
            }
        exams_by_subject[sid]["exams"].append({"id": ev["id"], "name": ev["name"]})

    # Determine selected exams for UI and filtering
    raw_exam_ids = request.GET.getlist("exam")
    selected_exam_ids: list[int] = []
    if raw_exam_ids:
        try:
            selected_exam_ids = [int(x) for x in raw_exam_ids if x.isdigit()]
        except Exception:
            selected_exam_ids = []
    elif request.user.is_authenticated:
        try:
            profile = StudentProfile.objects.select_related("user").get(user=request.user)
            selected_exam_ids = list(
                profile.exam_versions.values_list("id", flat=True)
            )
        except StudentProfile.DoesNotExist:
            selected_exam_ids = []

    qs = (
        Task.objects.all()
        .select_related("subject", "exam_version", "type")
        .prefetch_related("skills")
    )
    if selected_exam_ids:
        qs = qs.filter(exam_version_id__in=selected_exam_ids)

    # Dynamic/static filter
    kind = request.GET.get("kind", "all")
    if kind == "dynamic":
        qs = qs.filter(is_dynamic=True)
    elif kind == "static":
        qs = qs.filter(is_dynamic=False)

    # Sorting
    order = request.GET.get("order", "new")
    if order == "old":
        qs = qs.order_by("created_at")
    elif order == "hard":
        qs = qs.order_by("-difficulty_level", "-created_at")
    elif order == "easy":
        qs = qs.order_by("difficulty_level", "-created_at")
    elif order == "personal" and request.user.is_authenticated:
        # Create a stable ordering based on recommendation positions
        rec_list = recommend_tasks(request.user)
        rec_ids = [t.id for t in rec_list]
        # narrow to filtered set while preserving recommendation order
        current_ids = set(qs.values_list("id", flat=True))
        rec_ids = [pk for pk in rec_ids if pk in current_ids]
        if rec_ids:
            when_list = [When(id=pk, then=Value(idx)) for idx, pk in enumerate(rec_ids)]
            qs = qs.order_by(Case(*when_list, default=Value(len(rec_ids)), output_field=IntegerField()))
        else:
            qs = qs.order_by("-created_at")
    else:
        qs = qs.order_by("-created_at")

    context = {
        "tasks": qs,
        "exams_by_subject": exams_by_subject,
        "selected_exam_ids": selected_exam_ids,
        "kind": kind,
        "order": order,
    }
    return render(request, "recsys/tasks_list.html", context)


@staff_member_required
def variant_builder(request):
    """Staff-only page to assemble a variant with task filters."""

    def _parse_int(value: str | None) -> int | None:
        if not value:
            return None
        return int(value) if value.isdigit() else None

    subjects = list(Subject.objects.values("id", "name").order_by("name"))
    exam_versions = list(
        ExamVersion.objects.values("id", "subject_id", "name", "slug", "status").order_by(
            "subject__name", "name"
        )
    )
    sources = list(Source.objects.values("id", "slug", "name").order_by("name"))
    source_variants = list(
        SourceVariant.objects.values("id", "source_id", "slug", "label").order_by(
            "source__name", "label"
        )
    )

    selected_subject_id = _parse_int(request.GET.get("subject"))
    selected_exam_version_id = _parse_int(request.GET.get("exam_version"))
    selected_source_id = _parse_int(request.GET.get("source"))
    selected_source_variant_id = _parse_int(request.GET.get("source_variant"))

    if selected_exam_version_id:
        exam = (
            ExamVersion.objects.select_related("subject")
            .filter(id=selected_exam_version_id)
            .first()
        )
        if exam:
            selected_subject_id = exam.subject_id

    if selected_source_variant_id:
        variant = (
            SourceVariant.objects.select_related("source")
            .filter(id=selected_source_variant_id)
            .first()
        )
        if variant:
            selected_source_id = variant.source_id

    tasks_qs = Task.objects.select_related(
        "subject",
        "exam_version",
        "type",
        "source",
        "source_variant",
    )

    if selected_subject_id:
        tasks_qs = tasks_qs.filter(subject_id=selected_subject_id)
    if selected_exam_version_id:
        tasks_qs = tasks_qs.filter(exam_version_id=selected_exam_version_id)
    if selected_source_id:
        tasks_qs = tasks_qs.filter(source_id=selected_source_id)
    if selected_source_variant_id:
        tasks_qs = tasks_qs.filter(source_variant_id=selected_source_variant_id)

    tasks_qs = tasks_qs.order_by("type__display_order", "type__name", "id")

    context = {
        "subjects": subjects,
        "tasks": tasks_qs,
        "selected_subject_id": selected_subject_id,
        "selected_exam_version_id": selected_exam_version_id,
        "selected_source_id": selected_source_id,
        "selected_source_variant_id": selected_source_variant_id,
        "exam_versions_json": json.dumps(exam_versions, ensure_ascii=False),
        "sources_json": json.dumps(sources, ensure_ascii=False),
        "source_variants_json": json.dumps(source_variants, ensure_ascii=False),
    }
    return render(request, "recsys/variant_builder.html", context)


def _parse_int_query(value: str | None) -> int | None:
    if not value:
        return None
    return int(value) if value.isdigit() else None


def _get_safe_next(request) -> str:
    next_url = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if not next_url:
        return ""
    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return ""
    return next_url


@staff_member_required
def task_variant_map(request):
    subjects = list(Subject.objects.values("id", "name").order_by("name"))
    exam_versions = list(
        ExamVersion.objects.select_related("subject")
        .values("id", "subject_id", "name", "subject__name")
        .order_by("subject__name", "name")
    )

    selected_subject_id = _parse_int_query(request.GET.get("subject"))
    selected_exam_version_id = _parse_int_query(request.GET.get("exam_version"))
    selected_exam = None

    if selected_exam_version_id:
        selected_exam = (
            ExamVersion.objects.select_related("subject")
            .filter(id=selected_exam_version_id)
            .first()
        )
        if selected_exam:
            selected_subject_id = selected_exam.subject_id

    task_types: list[TaskType] = []
    source_sections: list[dict] = []
    no_source_row: dict | None = None

    if selected_subject_id and selected_exam_version_id and selected_exam:
        task_types = list(
            TaskType.objects.filter(
                subject_id=selected_subject_id,
                exam_version_id=selected_exam_version_id,
            )
            .order_by("display_order", "name", "id")
        )
        tasks = list(
            Task.objects.select_related("type", "source", "source_variant")
            .filter(
                subject_id=selected_subject_id,
                exam_version_id=selected_exam_version_id,
            )
            .order_by("-id")
        )

        by_source_variant_type: dict[tuple[int, int, int], list[Task]] = {}
        by_source_without_variant_type: dict[tuple[int, int], list[Task]] = {}
        by_no_source_type: dict[int, list[Task]] = {}

        for task in tasks:
            if task.source_id and task.source_variant_id:
                by_source_variant_type.setdefault(
                    (task.source_id, task.source_variant_id, task.type_id), []
                ).append(task)
            elif task.source_id:
                by_source_without_variant_type.setdefault(
                    (task.source_id, task.type_id), []
                ).append(task)
            else:
                by_no_source_type.setdefault(task.type_id, []).append(task)

        variants_by_source: dict[int, list[SourceVariant]] = {}
        for variant in SourceVariant.objects.select_related("source").order_by("source__name", "label", "id"):
            variants_by_source.setdefault(variant.source_id, []).append(variant)

        map_next = request.get_full_path()

        def _build_filled_cell(task_items: list[Task], task_type: TaskType) -> dict:
            task = task_items[0]
            redact_url = f"{reverse('tasks_redact')}?{urlencode({'task': task.id, 'next': map_next})}"
            return {
                "is_filled": True,
                "task": task,
                "task_type": task_type,
                "url": redact_url,
                "extra_count": max(len(task_items) - 1, 0),
            }

        def _build_empty_cell(
            task_type: TaskType,
            *,
            source_id: int | None,
            source_variant_id: int | None,
        ) -> dict:
            query = {
                "subject": selected_subject_id,
                "exam_version": selected_exam_version_id,
                "type": task_type.id,
                "next": map_next,
            }
            if source_id:
                query["source"] = source_id
            if source_variant_id:
                query["source_variant"] = source_variant_id
            upload_url = f"{reverse('tasks_upload')}?{urlencode(query)}"
            return {
                "is_filled": False,
                "task": None,
                "task_type": task_type,
                "url": upload_url,
                "extra_count": 0,
            }

        source_ids_in_tasks = {task.source_id for task in tasks if task.source_id}
        source_qs = (
            Source.objects.filter(
                Q(exam_version_id=selected_exam_version_id)
                | Q(id__in=source_ids_in_tasks)
            )
            .distinct()
            .order_by("name")
        )

        for source in source_qs:
            variant_rows: list[dict] = []
            for variant in variants_by_source.get(source.id, []):
                cells = []
                filled_count = 0
                for task_type in task_types:
                    items = by_source_variant_type.get((source.id, variant.id, task_type.id), [])
                    if items:
                        cell = _build_filled_cell(items, task_type)
                        filled_count += 1
                    else:
                        cell = _build_empty_cell(
                            task_type,
                            source_id=source.id,
                            source_variant_id=variant.id,
                        )
                    cells.append(cell)
                variant_rows.append(
                    {
                        "title": variant.label or variant.slug or f"Variant {variant.id}",
                        "is_without_variant": False,
                        "cells": cells,
                        "filled_count": filled_count,
                    }
                )

            without_variant_cells = []
            without_variant_filled = 0
            for task_type in task_types:
                items = by_source_without_variant_type.get((source.id, task_type.id), [])
                if items:
                    cell = _build_filled_cell(items, task_type)
                    without_variant_filled += 1
                else:
                    cell = _build_empty_cell(
                        task_type,
                        source_id=source.id,
                        source_variant_id=None,
                    )
                without_variant_cells.append(cell)

            if variant_rows or without_variant_filled:
                variant_rows.append(
                    {
                        "title": "Без варианта",
                        "is_without_variant": True,
                        "cells": without_variant_cells,
                        "filled_count": without_variant_filled,
                    }
                )
                source_sections.append(
                    {
                        "source": source,
                        "rows": variant_rows,
                    }
                )

        no_source_cells = []
        no_source_filled = 0
        for task_type in task_types:
            items = by_no_source_type.get(task_type.id, [])
            if items:
                cell = _build_filled_cell(items, task_type)
                no_source_filled += 1
            else:
                cell = _build_empty_cell(
                    task_type,
                    source_id=None,
                    source_variant_id=None,
                )
            no_source_cells.append(cell)
        no_source_row = {
            "title": "Без источника",
            "cells": no_source_cells,
            "filled_count": no_source_filled,
        }

    context = {
        "subjects": subjects,
        "exam_versions": exam_versions,
        "selected_subject_id": selected_subject_id,
        "selected_exam_version_id": selected_exam_version_id,
        "selected_exam": selected_exam,
        "task_types": task_types,
        "source_sections": source_sections,
        "no_source_row": no_source_row,
    }
    return render(request, "recsys/task_variant_map.html", context)


@staff_member_required
def task_upload(request):
    """
    Simple staff-only uploader for tasks with optional files (A/B) and image.
    """
    next_url = _get_safe_next(request)
    if request.method == "POST":
        form = TaskUploadForm(request.POST, request.FILES)
        if form.is_valid():
            task = form.create_task_with_attachments()
            messages.success(request, f"Задача создана: {task.slug}")
            if next_url:
                return redirect(next_url)
            return redirect("tasks_upload")
    else:
        initial: dict[str, int] = {}
        for key in ("subject", "exam_version", "type", "source", "source_variant"):
            parsed = _parse_int_query(request.GET.get(key))
            if parsed:
                initial[key] = parsed
        form = TaskUploadForm(initial=initial or None)

    context = _build_task_upload_context(form=form, next_url=next_url)
    return render(request, "recsys/task_upload.html", context)


def _build_task_upload_context(
    *,
    form: TaskUploadForm,
    redact_mode: bool = False,
    selected_task: Task | None = None,
    editable_tasks=None,
    next_url: str = "",
):
    exam_versions = list(
        ExamVersion.objects.values("id", "subject_id", "name", "slug", "status").order_by(
            "subject__name", "name"
        )
    )
    task_types = list(
        TaskType.objects.select_related("subject", "exam_version")
        .prefetch_related("required_tags")
        .order_by("subject__name", "exam_version__name", "name")
    )
    answer_schemas = {
        t.id: {
            "id": t.answer_schema.id,
            "name": t.answer_schema.name,
            "config": t.answer_schema.config,
        }
        for t in task_types
        if t.answer_schema
    }
    task_types_payload = [
        {
            "id": t.id,
            "subject_id": t.subject_id,
            "exam_version_id": t.exam_version_id,
            "name": t.name,
            "slug": t.slug,
            "answer_schema_id": t.answer_schema_id,
        }
        for t in task_types
    ]
    type_required_tags = {
        t.id: [{"id": tag.id, "name": tag.name} for tag in t.required_tags.all()]
        for t in task_types
    }
    skills = list(
        Skill.objects.values("id", "subject_id", "name").order_by("subject__name", "name")
    )
    skill_suggestions: dict[int, list[dict]] = {}
    suggestions_qs = (
        TaskSkill.objects.values(
            "task__type_id", "skill_id", "skill__name", "skill__subject_id"
        )
        .annotate(usage=Count("id"))
        .order_by("skill__name")
    )
    for entry in suggestions_qs:
        type_id = entry["task__type_id"]
        if not type_id:
            continue
        skill_suggestions.setdefault(type_id, []).append(
            {
                "id": entry["skill_id"],
                "name": entry["skill__name"],
                "subject_id": entry["skill__subject_id"],
                "usage": entry["usage"],
            }
        )

    sources = list(
        Source.objects.values("id", "slug", "name").order_by("name")
    )
    source_variants = list(
        SourceVariant.objects.values("id", "source_id", "slug", "label").order_by("source__name", "label")
    )

    return {
        "form": form,
        "redact_mode": redact_mode,
        "selected_task": selected_task,
        "editable_tasks": editable_tasks or [],
        "next_url": next_url,
        "exam_versions_json": json.dumps(exam_versions, ensure_ascii=False),
        "task_types_json": json.dumps(task_types_payload, ensure_ascii=False),
        "required_tags_json": json.dumps(type_required_tags, ensure_ascii=False),
        "skills_json": json.dumps(skills, ensure_ascii=False),
        "skill_suggestions_json": json.dumps(skill_suggestions, ensure_ascii=False),
        "answer_schemas_json": json.dumps(answer_schemas, ensure_ascii=False),
        "sources_json": json.dumps(sources, ensure_ascii=False),
        "source_variants_json": json.dumps(source_variants, ensure_ascii=False),
    }


@staff_member_required
def task_redact(request):
    next_url = _get_safe_next(request)
    selected_task_id = (request.POST.get("task_id") or request.GET.get("task") or "").strip()
    selected_task = None
    if selected_task_id.isdigit():
        selected_task = (
            Task.objects.select_related("subject", "exam_version", "type", "source", "source_variant")
            .prefetch_related("attachments")
            .filter(id=int(selected_task_id))
            .first()
        )

    if request.method == "POST":
        form = TaskUploadForm(request.POST, request.FILES, instance=selected_task)
        if not selected_task:
            messages.error(request, "Выберите задачу для редактирования.")
        elif form.is_valid():
            task = form.create_task_with_attachments()
            messages.success(request, f"Задача сохранена: {task.slug}")
            if next_url:
                return redirect(next_url)
            return redirect(f"{reverse('tasks_redact')}?task={task.id}")
    else:
        form = TaskUploadForm(instance=selected_task) if selected_task else TaskUploadForm()

    editable_tasks = list(
        Task.objects.select_related("subject", "exam_version", "type")
        .order_by("-id")
        .values("id", "slug", "title", "type__name", "exam_version__name", "subject__name")
    )
    context = _build_task_upload_context(
        form=form,
        redact_mode=True,
        selected_task=selected_task,
        editable_tasks=editable_tasks,
        next_url=next_url,
    )
    return render(request, "recsys/task_upload.html", context)
