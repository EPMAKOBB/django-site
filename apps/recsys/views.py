
import json

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Case, Count, IntegerField, Value, When
from django.shortcuts import get_object_or_404, redirect, render

from .models import (
    ExamVersion,
    Skill,
    SkillMastery,
    Source,
    SourceVariant,
    Task,
    TaskSkill,
    TaskTag,
    TaskType,
)
from .recommendation import recommend_tasks
from .forms import TaskUploadForm
from accounts.models import StudentProfile


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
        ExamVersion.objects.values("id", "subject_id", "name").order_by(
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
