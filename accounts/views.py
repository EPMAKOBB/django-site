from collections import defaultdict

from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.shortcuts import redirect, render

from apps.recsys.models import (
    ExamVersion,
    SkillGroup,
    SkillGroupItem,
    Task,
    TaskType,
)

from .forms import PasswordChangeForm, SignupForm, UserUpdateForm


def _get_dashboard_role(request):
    """Return the current dashboard role stored in the session.

    If no role is stored, infer it from the user's profiles and store it.
    """
    role = request.session.get("dashboard_role")
    if role not in {"student", "teacher"}:
        if hasattr(request.user, "teacherprofile") and not hasattr(
            request.user, "studentprofile"
        ):
            role = "teacher"
        else:
            role = "student"
        request.session["dashboard_role"] = role
    return role


def signup(request):
    """Register a new user and log them in."""
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("home")
    else:
        form = SignupForm()
    return render(request, "accounts/signup.html", {"form": form})


@login_required
def progress(request):
    """Temporary placeholder for the dashboard page."""
    role = _get_dashboard_role(request)
    context = {
        "active_tab": "tasks",
        "role": role,
    }
    return render(request, "accounts/dashboard.html", context)


@login_required
def dashboard_teachers(request):
    """Display a placeholder teachers dashboard."""
    role = _get_dashboard_role(request)
    context = {"active_tab": "teachers", "role": role}
    return render(request, "accounts/dashboard/teachers.html", context)


@login_required
def dashboard_classes(request):
    """Display a placeholder classes dashboard."""
    role = _get_dashboard_role(request)
    context = {"active_tab": "classes", "role": role}
    return render(request, "accounts/dashboard/classes.html", context)


@login_required
def dashboard_settings(request):
    role = _get_dashboard_role(request)
    if request.method == "POST":
        if "user_submit" in request.POST:
            u_form = UserUpdateForm(request.POST, instance=request.user)
            p_form = PasswordChangeForm(request.user)
            if u_form.is_valid():
                u_form.save()
                return redirect("accounts:dashboard-settings")
        elif "password_submit" in request.POST:
            u_form = UserUpdateForm(instance=request.user)
            p_form = PasswordChangeForm(request.user, request.POST)
            if p_form.is_valid():
                user = p_form.save()
                update_session_auth_hash(request, user)
                return redirect("accounts:dashboard-settings")
        elif "role_submit" in request.POST:
            new_role = request.POST.get("role")
            if new_role in {"student", "teacher"}:
                request.session["dashboard_role"] = new_role
            return redirect("accounts:dashboard-settings")
        else:
            u_form = UserUpdateForm(instance=request.user)
            p_form = PasswordChangeForm(request.user)
    else:
        u_form = UserUpdateForm(instance=request.user)
        p_form = PasswordChangeForm(request.user)
    context = {
        "u_form": u_form,
        "p_form": p_form,
        "active_tab": "settings",
        "role": role,
    }
    return render(request, "accounts/dashboard/settings.html", context)


@login_required
def dashboard_subjects(request):
    """Display a placeholder subjects dashboard."""
    role = _get_dashboard_role(request)

    skill_items = Prefetch(
        "items",
        queryset=SkillGroupItem.objects.select_related("skill").order_by("order"),
    )
    skill_groups_prefetch = Prefetch(
        "skill_groups",
        queryset=SkillGroup.objects.prefetch_related(skill_items).order_by("id"),
    )

    exams = list(
        ExamVersion.objects.select_related("subject")
        .prefetch_related(skill_groups_prefetch)
        .order_by("name")
    )

    exam_ids = [exam.id for exam in exams]
    subject_ids = {exam.subject_id for exam in exams}

    task_types_map = {
        task_type.id: task_type
        for task_type in TaskType.objects.filter(subject_id__in=subject_ids)
    }

    tasks_by_exam: dict[int, list[Task]] = defaultdict(list)
    for task in Task.objects.filter(exam_version_id__in=exam_ids).select_related(
        "type"
    ):
        tasks_by_exam[task.exam_version_id].append(task)

    exam_contexts = []
    for exam in exams:
        groups_data = []
        for group in exam.skill_groups.all():
            groups_data.append(
                {
                    "title": group.title,
                    "items": [
                        {
                            "label": item.label,
                            "skill_name": item.skill.name,
                        }
                        for item in group.items.all()
                    ],
                }
            )

        type_counts: dict[int, int] = defaultdict(int)
        for task in tasks_by_exam.get(exam.id, []):
            type_counts[task.type_id] += 1

        type_entries = []
        for type_id, count in type_counts.items():
            task_type = task_types_map.get(type_id)
            if task_type is None:
                continue
            type_entries.append(
                {
                    "id": type_id,
                    "name": task_type.name,
                    "description": task_type.description,
                    "task_count": count,
                }
            )

        type_entries.sort(key=lambda entry: entry["name"])

        stats = {
            "group_count": len(groups_data),
            "skill_count": sum(len(group["items"]) for group in groups_data),
            "task_type_count": len(type_entries),
            "task_count": sum(entry["task_count"] for entry in type_entries),
        }

        exam_contexts.append(
            {
                "id": exam.id,
                "name": exam.name,
                "subject": exam.subject.name,
                "skill_groups": groups_data,
                "task_types": type_entries,
                "stats": stats,
            }
        )

    context = {
        "active_tab": "subjects",
        "role": role,
        "exams": exam_contexts,
    }
    return render(request, "accounts/dashboard/subjects.html", context)


@login_required
def dashboard_courses(request):
    """Display a placeholder courses dashboard."""
    role = _get_dashboard_role(request)
    context = {"active_tab": "courses", "role": role}
    return render(request, "accounts/dashboard/courses.html", context)

