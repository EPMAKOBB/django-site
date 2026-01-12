
import json

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Case, Count, IntegerField, Value, When
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
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
from accounts.models import StudentProfile
from apps.recsys.service_utils import variants as variant_services
from apps.recsys.service_utils.type_progress import build_type_progress_map


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
    masteries = (
        SkillMastery.objects.filter(user=student)
        .select_related("skill")
        .order_by("skill__name")
    )
    context = {"student": student, "skill_masteries": masteries}
    return render(request, "recsys/teacher_user.html", context)


def exam_page(request, exam_slug: str):
    """Public exam landing with personal variant builder."""

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
    blueprint = (
        ExamBlueprint.objects.filter(exam_version=exam, is_active=True)
        .prefetch_related("items__task_type")
        .order_by("-updated_at", "-id")
        .first()
    )

    if request.method == "POST" and request.POST.get("action") == "build_personal":
        if not request.user.is_authenticated:
            return redirect(f"{reverse('accounts:login')}?next={request.path}")
        try:
            assignment = variant_services.build_personal_assignment_from_blueprint(
                user=request.user,
                exam_version=exam,
            )
        except drf_exceptions.ValidationError as exc:
            detail = getattr(exc, "detail", None) or getattr(exc, "args", None)
            messages.error(request, str(detail or exc))
        else:
            page = variant_services.ensure_variant_page(assignment.template, is_public=False)
            return redirect("variant-page", slug=page.slug)

    task_types = list(
        TaskType.objects.filter(exam_version=exam).order_by("display_order", "name")
    )
    blueprint_items: dict[int, object] = {}
    if blueprint:
        blueprint_items = {item.task_type_id: item for item in blueprint.items.all()}

    static_variants = (
        VariantTemplate.objects.filter(
            exam_version=exam,
            is_public=True,
            page__is_public=True,
        )
        .select_related("page")
        .order_by("display_order", "name")
    )

    type_progress = {}
    skill_masteries = []
    if request.user.is_authenticated:
        type_progress = build_type_progress_map(
            user=request.user,
            task_type_ids=[t.id for t in task_types],
        )
        skill_masteries = list(
            SkillMastery.objects.filter(
                user=request.user,
                skill__subject=exam.subject,
            )
            .select_related("skill")
            .order_by("-mastery", "skill__name")
        )

    task_rows = []
    for task_type in task_types:
        progress = type_progress.get(task_type.id) if type_progress else None
        task_rows.append(
            {
                "type": task_type,
                "item": blueprint_items.get(task_type.id),
                "progress": progress,
                "progress_pct": int(round((progress.effective_mastery or 0) * 100))
                if progress
                else 0,
            }
        )

    context = {
        "exam": exam,
        "blueprint": blueprint,
        "task_rows": task_rows,
        "static_variants": static_variants,
        "type_progress": type_progress,
        "skill_masteries": skill_masteries,
    }
    return render(request, "exams/detail.html", context)


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
            messages.error(request, str(getattr(exc, "detail", exc)))
        except drf_exceptions.APIException as exc:
            messages.error(request, str(getattr(exc, "detail", exc)))
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
def task_upload(request):
    """
    Simple staff-only uploader for tasks with optional files (A/B) and image.
    """
    if request.method == "POST":
        form = TaskUploadForm(request.POST, request.FILES)
        if form.is_valid():
            task = form.create_task_with_attachments()
            messages.success(request, f"Задача создана: {task.slug}")
            return redirect("tasks_upload")
    else:
        form = TaskUploadForm()

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

    return render(
        request,
        "recsys/task_upload.html",
        {
            "form": form,
            "exam_versions_json": json.dumps(exam_versions, ensure_ascii=False),
            "task_types_json": json.dumps(task_types_payload, ensure_ascii=False),
            "required_tags_json": json.dumps(type_required_tags, ensure_ascii=False),
            "skills_json": json.dumps(skills, ensure_ascii=False),
            "skill_suggestions_json": json.dumps(skill_suggestions, ensure_ascii=False),
            "answer_schemas_json": json.dumps(answer_schemas, ensure_ascii=False),
            "sources_json": json.dumps(sources, ensure_ascii=False),
            "source_variants_json": json.dumps(source_variants, ensure_ascii=False),
        },
    )
