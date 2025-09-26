import logging

from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import exceptions as drf_exceptions

from apps.recsys.models import (
    ExamVersion,
    Skill,
    SkillMastery,
    Task,
    TaskSkill,
    TaskType,
    TypeMastery,
)
from apps.recsys.service_utils import variants as variant_services
from subjects.models import Subject

from .forms import (
    PasswordChangeForm,
    SignupForm,
    TaskCreateForm,
    UserUpdateForm,
    build_task_skill_formset,
)
from .forms_exams import ExamPreferencesForm
from .models import StudentProfile


logger = logging.getLogger("accounts")


def _format_error_detail(detail) -> str:
    if isinstance(detail, (list, tuple)):
        return " ".join(str(item) for item in detail)
    if isinstance(detail, dict):
        return " ".join(str(value) for value in detail.values())
    return str(detail)


def _active_attempt(assignment):
    for attempt in assignment.attempts.all():
        if attempt.completed_at is None:
            return attempt
    return None


def _build_assignment_context(assignment):
    progress = variant_services.calculate_assignment_progress(assignment)
    total_tasks = progress.get("total_tasks") or 0
    solved_tasks = progress.get("solved_tasks") or 0
    if total_tasks:
        progress_percentage = int(round((solved_tasks / total_tasks) * 100))
    else:
        progress_percentage = 0

    active_attempt = _active_attempt(assignment)
    attempts_used = assignment.attempts.count()
    attempts_total = assignment.template.max_attempts
    attempts_left = variant_services.get_attempts_left(assignment)
    deadline = assignment.deadline
    deadline_passed = bool(deadline and deadline < timezone.now())

    return {
        "assignment": assignment,
        "progress": progress,
        "progress_percentage": progress_percentage,
        "active_attempt": active_attempt,
        "attempts_used": attempts_used,
        "attempts_total": attempts_total,
        "attempts_left": attempts_left,
        "can_start": variant_services.can_start_attempt(assignment),
        "deadline": deadline,
        "deadline_passed": deadline_passed,
    }

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
    """Render the assignments dashboard with current and past items."""

    role = _get_dashboard_role(request)
    assignments = variant_services.get_assignments_for_user(request.user)
    current_assignments, past_assignments = variant_services.split_assignments(assignments)

    context = {
        "active_tab": "tasks",
        "role": role,
        "current_assignments": [
            _build_assignment_context(assignment) for assignment in current_assignments
        ],
        "past_assignments": [
            _build_assignment_context(assignment) for assignment in past_assignments
        ],
    }
    return render(request, "accounts/dashboard.html", context)


@login_required
def assignment_detail(request, assignment_id: int):
    """Show assignment details and allow starting a new attempt."""

    role = _get_dashboard_role(request)
    try:
        assignment = variant_services.get_assignment_or_404(request.user, assignment_id)
    except drf_exceptions.NotFound as exc:
        raise Http404(str(exc)) from exc

    if request.method == "POST" and "start_attempt" in request.POST:
        try:
            variant_services.start_new_attempt(request.user, assignment_id)
        except drf_exceptions.ValidationError as exc:
            messages.error(request, _format_error_detail(exc.detail))
        else:
            messages.success(request, _("Новая попытка по варианту начата"))
            return redirect("accounts:assignment-detail", assignment_id=assignment_id)

    context = {
        "active_tab": "tasks",
        "role": role,
        "assignment": assignment,
        "assignment_info": _build_assignment_context(assignment),
        "attempts": assignment.attempts.all(),
    }
    return render(
        request,
        "accounts/dashboard/assignment_detail.html",
        context,
    )


@login_required
def assignment_result(request, assignment_id: int):
    """Display the attempts history for the assignment."""

    role = _get_dashboard_role(request)
    try:
        assignment = variant_services.get_assignment_history(request.user, assignment_id)
    except drf_exceptions.NotFound as exc:
        raise Http404(str(exc)) from exc

    context = {
        "active_tab": "tasks",
        "role": role,
        "assignment": assignment,
        "assignment_info": _build_assignment_context(assignment),
        "attempts": assignment.attempts.all(),
    }
    return render(
        request,
        "accounts/dashboard/assignment_result.html",
        context,
    )


@login_required
def dashboard_teachers(request):
    """Display the teacher dashboard with a form for creating tasks."""

    if not hasattr(request.user, "teacherprofile"):
        raise PermissionDenied("Only teachers can access this section")

    role = _get_dashboard_role(request)
    if role != "teacher":
        role = "teacher"
        request.session["dashboard_role"] = role

    subject_obj = None
    if request.method == "POST":
        form = TaskCreateForm(request.POST, request.FILES)
        subject_id = request.POST.get("subject")
        if subject_id:
            try:
                subject_obj = Subject.objects.get(pk=subject_id)
            except (Subject.DoesNotExist, ValueError, TypeError):
                subject_obj = None
        skill_formset = build_task_skill_formset(
            subject=subject_obj, data=request.POST, prefix="skills"
        )
        if form.is_valid() and skill_formset.is_valid():
            subject = form.cleaned_data["subject"]
            cleaned_skills: list[tuple[Skill, float]] = []
            seen_skill_ids: set[int] = set()
            formset_has_errors = False

            for skill_form in skill_formset:
                if not getattr(skill_form, "cleaned_data", None):
                    continue
                if skill_form.cleaned_data.get("DELETE"):
                    continue
                skill = skill_form.cleaned_data.get("skill")
                if not skill:
                    continue
                if skill.subject_id != subject.id:
                    skill_form.add_error(
                        "skill",
                        _("Умение должно относиться к выбранному предмету."),
                    )
                    formset_has_errors = True
                    continue
                if skill.id in seen_skill_ids:
                    skill_form.add_error(
                        "skill",
                        _("Это умение уже добавлено."),
                    )
                    formset_has_errors = True
                    continue
                weight = float(skill_form.cleaned_data.get("weight") or 1)
                cleaned_skills.append((skill, weight))
                seen_skill_ids.add(skill.id)

            if not formset_has_errors:
                with transaction.atomic():
                    task = form.save()
                    TaskSkill.objects.filter(task=task).delete()
                    for skill, weight in cleaned_skills:
                        TaskSkill.objects.create(task=task, skill=skill, weight=weight)
                messages.success(request, _("Задача успешно сохранена."))
                return redirect("accounts:dashboard-teachers")
    else:
        form = TaskCreateForm()
        skill_formset = build_task_skill_formset(subject=None, prefix="skills")

    context = {
        "active_tab": "teachers",
        "role": role,
        "form": form,
        "skill_formset": skill_formset,
    }
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
    """Display all courses the current user is enrolled in."""

    role = _get_dashboard_role(request)

    from courses.services import build_course_graph

    enrollments = list(
        request.user.course_enrollments.select_related("course").order_by("-enrolled_at")
    )

    for enrollment in enrollments:
        enrollment.graph = build_course_graph(request.user, enrollment.course)

    context = {
        "active_tab": "courses",
        "role": role,
        "enrollments": enrollments,
    }
    return render(request, "accounts/dashboard/courses.html", context)





