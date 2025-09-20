import logging
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from .forms import SignupForm, UserUpdateForm, PasswordChangeForm
from .forms_exams import ExamPreferencesForm
from .models import StudentProfile
from apps.recsys.forms import TaskCreateForm
from subjects.models import Subject
from apps.recsys.models import (
    SkillMastery,
    TypeMastery,
    ExamVersion,
    TaskType,
)


logger = logging.getLogger("accounts")

def _get_dashboard_role(request):
    """Return the current dashboard role stored in the session."""

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


def _get_selected_exam_ids(
    profile: StudentProfile | None, exams_form: ExamPreferencesForm
) -> list[int]:
    """Return the exam ids that should be rendered as selected."""

    def _normalize(values) -> list[int]:
        normalized: list[int] = []
        for value in values:
            if value is None:
                continue
            try:
                normalized.append(int(value))
            except (TypeError, ValueError):
                continue
        return normalized

    if exams_form.is_bound:
        return _normalize(exams_form.data.getlist("exam_versions"))
    if profile:
        return list(profile.exam_versions.values_list("id", flat=True))
    return []


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
def dashboard_teacher_room(request):
    """Display the teacher room with the task creation form."""

    role = _get_dashboard_role(request)
    if role != "teacher":
        messages.warning(request, _("Раздел доступен только преподавателям."))
        return redirect("accounts:dashboard")

    initial = {}
    subject_param = request.GET.get("subject")
    if subject_param:
        initial["subject"] = subject_param

    if request.method == "POST":
        form = TaskCreateForm(request.POST, request.FILES)
        if form.is_valid():
            task = form.save()
            messages.success(request, _("Задача сохранена"))
            redirect_url = reverse("accounts:dashboard-teacher-room")
            if task.subject_id:
                redirect_url = f"{redirect_url}?subject={task.subject_id}"
            return redirect(redirect_url)
    else:
        form = TaskCreateForm(initial=initial)

    context = {
        "active_tab": "teacher-room",
        "role": role,
        "task_form": form,
    }
    return render(request, "accounts/dashboard/teacher_room.html", context)


@login_required
def dashboard_classes(request):
    """Display a placeholder classes dashboard."""

    role = _get_dashboard_role(request)
    context = {"active_tab": "classes", "role": role}
    return render(request, "accounts/dashboard/classes.html", context)


@login_required
def dashboard_settings(request):
    role = _get_dashboard_role(request)
    profile, _created = StudentProfile.objects.get_or_create(user=request.user)
    subjects_qs = Subject.objects.all().prefetch_related("exam_versions").order_by("name")

    if request.method == "POST":
        form_type = request.POST.get("form_type")
        user_submit = "user_submit" in request.POST
        password_submit = "password_submit" in request.POST
        role_submit = "role_submit" in request.POST
        exams_submit = "exams_submit" in request.POST

        if user_submit:
            u_form = UserUpdateForm(request.POST, instance=request.user)
            p_form = PasswordChangeForm(request.user)
            exams_form = ExamPreferencesForm(instance=profile)
            if u_form.is_valid():
                u_form.save()
                return redirect("accounts:dashboard-settings")
        elif password_submit:
            u_form = UserUpdateForm(instance=request.user)
            p_form = PasswordChangeForm(request.user, request.POST)
            exams_form = ExamPreferencesForm(instance=profile)
            if p_form.is_valid():
                user = p_form.save()
                update_session_auth_hash(request, user)
                return redirect("accounts:dashboard-settings")
        elif role_submit:
            new_role = request.POST.get("role")
            if new_role in {"student", "teacher"}:
                request.session["dashboard_role"] = new_role
            return redirect("accounts:dashboard-settings")
        elif (
            form_type == "exams"
            or exams_submit
            or not (user_submit or password_submit or role_submit)
        ):
            u_form = UserUpdateForm(instance=request.user)
            p_form = PasswordChangeForm(request.user)
            exams_form = ExamPreferencesForm(request.POST, instance=profile)
            raw_ids = request.POST.getlist("exam_versions")
            ids = []
            for v in raw_ids:
                try:
                    ids.append(int(v))
                except (TypeError, ValueError):
                    continue
            logger.debug(
                "Received exam selection payload",
                extra={
                    "raw_ids": raw_ids,
                    "normalized_ids": ids,
                    "user_id": request.user.pk,
                    "profile_id": profile.pk,
                },
            )
            selected = ExamVersion.objects.filter(id__in=ids)
            logger.debug(
                "ExamVersion queryset after filtering",
                extra={
                    "selected_ids": list(selected.values_list("id", flat=True)),
                    "user_id": request.user.pk,
                    "profile_id": profile.pk,
                },
            )
            profile.exam_versions.set(selected)
            logger.debug(
                "Profile exam versions updated",
                extra={
                    "stored_ids": list(profile.exam_versions.values_list("id", flat=True)),
                    "user_id": request.user.pk,
                    "profile_id": profile.pk,
                },
            )
            messages.success(request, _("Выбор сохранён"))
            return redirect("accounts:dashboard-settings")
        else:
            u_form = UserUpdateForm(instance=request.user)
            p_form = PasswordChangeForm(request.user)
            exams_form = ExamPreferencesForm(instance=profile)
    else:
        u_form = UserUpdateForm(instance=request.user)
        p_form = PasswordChangeForm(request.user)
        exams_form = ExamPreferencesForm(instance=profile)

    selected_exams = (
        profile.exam_versions.select_related("subject")
        .order_by("subject__name", "name")
    )

    selected_exam_ids = _get_selected_exam_ids(profile, exams_form)
    db_selected_exam_ids = list(profile.exam_versions.values_list("id", flat=True))

    context = {
        "u_form": u_form,
        "p_form": p_form,
        "exams_form": exams_form,
        "subjects": subjects_qs,
        "selected_exam_ids": selected_exam_ids,
        "selected_exams": selected_exams,
        "active_tab": "settings",
        "role": role,
    }
    through_records = list(
        profile.exam_versions.through.objects.filter(studentprofile=profile).values_list(
            "id", "examversion_id"
        )
    )
    logger.debug(
        "Rendering dashboard settings: profile_id=%s user_id=%s selected_exam_ids=%s db_selected_exam_ids=%s",
        profile.pk,
        request.user.pk,
        selected_exam_ids,
        db_selected_exam_ids,
    )
    logger.info(
        "Dashboard settings context: alias=%s profile_id=%s user_id=%s selected_exam_ids=%s db_selected_exam_ids=%s through_records=%s",
        connection.alias,
        profile.pk,
        request.user.pk,
        selected_exam_ids,
        db_selected_exam_ids,
        through_records,
    )
    return render(request, "accounts/dashboard/settings.html", context)


@login_required
def dashboard_subjects(request):
    """Subjects dashboard with collapsible subject blocks and progress."""

    role = _get_dashboard_role(request)

    profile, _ = StudentProfile.objects.get_or_create(user=request.user)

    selected_exams = (
        profile.exam_versions.select_related("subject")
        .prefetch_related("skill_groups__items__skill")
        .order_by("subject__name", "name")
    )

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

    subject_ids = {exam.subject_id for exam in selected_exams}
    types_by_subject: dict[int, list[TaskType]] = {}
    if subject_ids:
        task_types = (
            TaskType.objects.filter(subject_id__in=subject_ids)
            .select_related("subject")
            .order_by("subject__name", "name")
        )
        for task_type in task_types:
            types_by_subject.setdefault(task_type.subject_id, []).append(task_type)

    exam_statistics = []
    for exam in selected_exams:
        exam_statistics.append(
            {
                "subject": exam.subject,
                "exam_version": exam,
                "groups": list(exam.skill_groups.all()),
                "types": types_by_subject.get(exam.subject_id, []),
                "skill_masteries": mastery_by_skill_id,
                "type_masteries": mastery_by_type_id,
            }
        )

    context = {
        "active_tab": "statistics",
        "role": role,
        "exam_statistics": exam_statistics,
    }
    return render(request, "accounts/dashboard/subjects.html", context)


@login_required
def dashboard_courses(request):
    """Display a placeholder courses dashboard."""

    role = _get_dashboard_role(request)
    context = {"active_tab": "courses", "role": role}
    return render(request, "accounts/dashboard/courses.html", context)





