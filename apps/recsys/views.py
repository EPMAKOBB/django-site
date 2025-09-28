
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Case, IntegerField, Value, When
from django.shortcuts import get_object_or_404, render

from .models import ExamVersion, SkillMastery, Task
from .recommendation import recommend_tasks
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
