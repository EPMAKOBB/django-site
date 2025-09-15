from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect


from .forms import SignupForm, UserUpdateForm, PasswordChangeForm
from subjects.models import Subject
from apps.recsys.models import (
    SkillMastery,
    TypeMastery,
    SkillGroup,
    ExamVersion,
    TaskType,
)


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
    """Subjects dashboard with collapsible subject blocks and progress.

    For each subject:
      - Skill progress by skill (via SkillMastery)
      - Task-type progress (via TypeMastery)
      - Skill groups for the latest exam version, if configured
    """
    role = _get_dashboard_role(request)

    subjects = Subject.objects.all().order_by("name")

    # Preload user masteries once and index by related id
    skill_masteries = (
        SkillMastery.objects.filter(user=request.user)
        .select_related("skill", "skill__subject")
    )
    type_masteries = (
        TypeMastery.objects.filter(user=request.user)
        .select_related("task_type", "task_type__subject")
    )

    mastery_by_skill_id: dict[int, float] = {
        sm.skill_id: float(sm.mastery) for sm in skill_masteries
    }
    mastery_by_type_id: dict[int, float] = {
        tm.task_type_id: float(tm.mastery) for tm in type_masteries
    }

    subjects_data = []
    for subj in subjects:
        # Try to pick a default exam version for groups (first by name)
        exam_version = (
            ExamVersion.objects.filter(subject=subj).order_by("name").first()
        )
        groups = []
        if exam_version:
            groups = (
                SkillGroup.objects.filter(exam_version=exam_version)
                .prefetch_related("items__skill")
                .order_by("id")
            )

        types = TaskType.objects.filter(subject=subj).order_by("name")

        subjects_data.append(
            {
                "subject": subj,
                "exam_version": exam_version,
                "groups": groups,
                "types": types,
                "skill_masteries": mastery_by_skill_id,
                "type_masteries": mastery_by_type_id,
            }
        )

    context = {
        "active_tab": "subjects",
        "role": role,
        "subjects_data": subjects_data,
    }
    return render(request, "accounts/dashboard/subjects.html", context)


@login_required
def dashboard_courses(request):
    """Display a placeholder courses dashboard."""
    role = _get_dashboard_role(request)
    context = {"active_tab": "courses", "role": role}
    return render(request, "accounts/dashboard/courses.html", context)

