import json
import logging
from collections import defaultdict
from datetime import timedelta

from django.contrib import messages
from django.conf import settings
from django.contrib.auth import get_user_model, login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Max, Prefetch, Q
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import exceptions as drf_exceptions

from apps.recsys.models import (
    Attempt,
    Skill,
    Task,
    TaskSkill,
    TrainingSession,
    TrainingSessionStep,
    VariantAttempt,
    VariantTemplate,
    VariantAssignment,
    VariantTaskAttempt,
    VariantTask,
)
from apps.recsys.service_utils import variants as variant_services
from apps.recsys.service_utils.type_progress import build_type_progress_map
from subjects.models import Subject
from courses.models import CourseGraphEdge, CourseModule, CourseModuleItem
from .context_processors import SESSION_KEY
from courses.services import (
    MODULE_UNLOCK_PROGRESS_THRESHOLD,
    build_module_progress_map,
    is_module_unlocked_for_user,
)

from .forms import (
    LoginForm,
    PasswordChangeForm,
    SignupForm,
    TaskCreateForm,
    UserUpdateForm,
    build_task_skill_formset,
    CourseForm,
    CourseTheoryCardForm,
)
from .models import (
    StudyClass,
    ClassStudentMembership,
    ClassTeacherSubject,
    TeacherStudentLink,
    TeacherSubjectInvite,
    teacher_has_subject_access,
)


logger = logging.getLogger("accounts")


def _get_safe_redirect(request, fallback: str | None = None) -> str:
    candidate = request.POST.get("next") or request.GET.get("next") or fallback or settings.LOGIN_REDIRECT_URL
    if url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return candidate
    return fallback or settings.LOGIN_REDIRECT_URL


def _format_error_detail(detail) -> str:
    if isinstance(detail, (list, tuple)):
        return " ".join(str(item) for item in detail)
    if isinstance(detail, dict):
        return " ".join(str(value) for value in detail.values())
    return str(detail)


def _stringify_response(value):
    if value is None or value == '':
        return ''
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:  # pragma: no cover - defensive
        return str(value)


def _format_duration(value: timedelta) -> str:
    total_seconds = int(value.total_seconds())
    if total_seconds < 0:
        total_seconds = 0
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _active_attempt(assignment):
    for attempt in assignment.attempts.all():
        if attempt.completed_at is None:
            return attempt
    return None


def _latest_completed_attempt(assignment):
    completed_attempts = [
        attempt for attempt in assignment.attempts.all() if attempt.completed_at is not None
    ]
    if not completed_attempts:
        return None
    return max(completed_attempts, key=lambda attempt: attempt.completed_at)


def _build_assignment_context(assignment):
    progress = variant_services.calculate_assignment_progress(assignment)
    total_tasks = progress.get("total_tasks") or 0
    solved_tasks = progress.get("solved_tasks") or 0
    if total_tasks:
        progress_percentage = int(round((solved_tasks / total_tasks) * 100))
    else:
        progress_percentage = 0

    active_attempt = _active_attempt(assignment)
    latest_completed_attempt = _latest_completed_attempt(assignment)
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
        "latest_completed_attempt": latest_completed_attempt,
        "attempts_used": attempts_used,
        "attempts_total": attempts_total,
        "attempts_left": attempts_left,
        "can_start": variant_services.can_start_attempt(assignment),
        "deadline": deadline,
        "deadline_passed": deadline_passed,
        "history_at": (
            latest_completed_attempt.completed_at
            if latest_completed_attempt
            else assignment.updated_at or assignment.created_at
        ),
    }


def _result_label(result: str) -> str:
    labels = {
        "correct": _("верно"),
        "partial": _("частично"),
        "incorrect": _("ошибка"),
        "unknown": _("без оценки"),
    }
    return labels.get(result, result or _("без оценки"))


def _build_training_step_context(step):
    task_snapshot = step.task_snapshot or {}
    attempt = step.attempt
    score = attempt.score if attempt else None
    max_score = (attempt.max_score if attempt else None) or task_snapshot.get("max_score")
    if score is not None and max_score:
        score_label = f"{score} / {max_score}"
    elif score is not None:
        score_label = str(score)
    else:
        score_label = "—"
    return {
        "step": step,
        "task_title": task_snapshot.get("title") or (step.task.title if step.task else _("Задача")),
        "task_type_name": task_snapshot.get("task_type_name") or (step.task.type.name if step.task and step.task.type_id else ""),
        "result_label": _result_label(step.result),
        "response": _stringify_response((step.response_snapshot or {}).get("answer")),
        "score_label": score_label,
    }


def _build_training_session_context(session):
    completed_steps = session.completed_steps or 0
    correct_steps = session.correct_steps or 0
    accuracy_percentage = int(round((correct_steps / completed_steps) * 100)) if completed_steps else 0
    steps = [
        _build_training_step_context(step)
        for step in session.steps.all()
        if step.status == "answered"
    ]
    type_names = []
    for item in steps:
        name = item.get("task_type_name")
        if name and name not in type_names:
            type_names.append(name)

    status_labels = {
        TrainingSession.Status.ACTIVE: _("в работе"),
        TrainingSession.Status.COMPLETED: _("завершена"),
        TrainingSession.Status.ABANDONED: _("прервана"),
    }
    exam = session.exam_version
    return {
        "session": session,
        "exam": exam,
        "title": _("Тренировка"),
        "status_label": status_labels.get(session.status, session.status),
        "steps": steps,
        "type_names": type_names,
        "accuracy_percentage": accuracy_percentage,
        "progress_label": f"{correct_steps}/{completed_steps}" if completed_steps else "0/0",
        "activity_at": session.last_activity_at or session.ended_at or session.started_at,
        "continue_url": reverse("exam-training-page", args=[exam.slug]) if exam and exam.slug else "",
    }


def _get_dashboard_role(request):
    """Return the current dashboard role stored in the session."""

    allowed = {"student", "teacher", "methodist"}
    role = request.session.get("dashboard_role")
    if role not in allowed:
        # Choose a default based on available profiles: teacher > methodist > student
        if hasattr(request.user, "teacherprofile") and not hasattr(request.user, "studentprofile"):
            role = "teacher"
        elif hasattr(request.user, "methodistprofile") and not hasattr(request.user, "studentprofile"):
            role = "methodist"
        else:
            role = "student"
        request.session["dashboard_role"] = role
    return role


def auth_entry(request, default_mode: str = "login"):
    """Render a shared auth page with login and signup blocks."""

    if request.user.is_authenticated:
        return redirect(_get_safe_redirect(request, fallback=reverse("accounts:dashboard")))

    active_mode = default_mode if default_mode in {"login", "signup"} else "login"
    login_form = LoginForm(request=request, prefix="login")
    signup_form = SignupForm(prefix="signup")

    if request.method == "POST":
        action = request.POST.get("auth_action")
        if action == "login":
            active_mode = "login"
            login_form = LoginForm(request=request, data=request.POST, prefix="login")
            signup_form = SignupForm(prefix="signup")
            if login_form.is_valid():
                user = login_form.get_user()
                login(request, user)
                return redirect(_get_safe_redirect(request))
        elif action == "signup":
            active_mode = "signup"
            login_form = LoginForm(request=request, prefix="login")
            signup_form = SignupForm(request.POST, prefix="signup")
            if signup_form.is_valid():
                user = signup_form.save()
                login(request, user)
                return redirect(_get_safe_redirect(request))

    context = {
        "active_mode": active_mode,
        "login_form": login_form,
        "signup_form": signup_form,
        "next_url": _get_safe_redirect(request, fallback=""),
    }
    return render(request, "accounts/auth.html", context)


@login_required
def progress(request):
    """Render the assignments dashboard with current and past items."""

    role = _get_dashboard_role(request)
    assignments = variant_services.get_assignments_for_user(request.user)
    current_assignments, past_assignments = variant_services.split_assignments(assignments)
    training_sessions = list(
        TrainingSession.objects.filter(
            user=request.user,
        )
        .select_related("exam_version", "exam_version__subject")
        .prefetch_related("steps", "steps__task", "steps__task__type", "steps__attempt")
        .order_by("-last_activity_at", "-started_at", "-id")[:50]
    )
    active_training_sessions = [
        session for session in training_sessions if session.status == TrainingSession.Status.ACTIVE
    ]
    past_training_sessions = [
        session for session in training_sessions if session.status != TrainingSession.Status.ACTIVE
    ]
    current_assignment_contexts = [
        _build_assignment_context(assignment) for assignment in current_assignments
    ]
    past_assignment_contexts = [
        _build_assignment_context(assignment) for assignment in past_assignments
    ]
    active_training_contexts = [
        _build_training_session_context(session) for session in active_training_sessions
    ]
    past_training_contexts = [
        _build_training_session_context(session) for session in past_training_sessions
    ]
    history_entries = [
        {
            "kind": "training",
            "sort_at": item["activity_at"],
            "item": item,
        }
        for item in past_training_contexts
    ] + [
        {
            "kind": "assignment",
            "sort_at": item["history_at"],
            "item": item,
        }
        for item in past_assignment_contexts
    ]
    history_entries.sort(
        key=lambda entry: entry["sort_at"] or timezone.now(),
        reverse=True,
    )

    context = {
        "active_tab": "tasks",
        "role": role,
        "current_assignments": current_assignment_contexts,
        "past_assignments": past_assignment_contexts,
        "active_training_sessions": active_training_contexts,
        "past_training_sessions": past_training_contexts,
        "history_entries": history_entries,
        "active_count": len(current_assignments) + len(active_training_sessions),
        "history_count": len(past_assignments) + len(past_training_sessions),
    }
    return render(request, "accounts/dashboard.html", context)


@login_required
def assignment_detail(request, assignment_id: int):
    """Show assignment details and allow starting a new attempt."""

    role = _get_dashboard_role(request)
    try:
        assignment = variant_services.get_assignment_or_404(request.user, assignment_id)
    except drf_exceptions.NotFound as exc:
        logger.warning("Assignment not found", extra={"assignment_id": assignment_id}, exc_info=exc)
        raise Http404("Not found") from exc

    if request.method == "POST" and "start_attempt" in request.POST:
        try:
            attempt = variant_services.start_new_attempt(request.user, assignment_id)
        except drf_exceptions.ValidationError as exc:
            logger.info("Assignment start validation error", extra={"assignment_id": assignment_id}, exc_info=exc)
            messages.error(request, _("Не удалось начать попытку."))
        else:
            messages.success(request, _("Новая попытка по варианту начата"))
            return redirect("accounts:variant-attempt-solver", attempt_id=attempt.id)

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
        logger.warning("Assignment history not found", extra={"assignment_id": assignment_id}, exc_info=exc)
        raise Http404("Not found") from exc

    attempts = assignment.attempts.all()
    exam_mismatch_notice = None
    completed_attempts = [attempt for attempt in attempts if attempt.completed_at]
    if completed_attempts:
        latest_completed = max(
            completed_attempts,
            key=lambda attempt: attempt.completed_at or attempt.started_at,
        )
        matches_blueprint, _ = variant_services.template_matches_blueprint(
            assignment.template
        )
        if not matches_blueprint:
            summary = variant_services.calculate_attempt_primary_summary(latest_completed)
            scale = variant_services.get_active_score_scale(
                assignment.template.exam_version
            )
            primary_total = summary["primary_total"]
            success_percent = summary["success_percent"]
            success_percent_text = f"{success_percent:.1f}".rstrip("0").rstrip(".")
            secondary_score = None
            over_limit = False
            if scale:
                secondary_score, over_limit = scale.to_secondary(primary_total)

            if over_limit:
                exam_mismatch_notice = (
                    "Вариант не соответствует экзамену, за эти задачи вы набрали "
                    f"{primary_total} первичных баллов, что соответствует больше "
                    "100 вторичных баллов, процент успеха "
                    f"{success_percent_text}%."
                )
            elif secondary_score is not None:
                exam_mismatch_notice = (
                    "Вариант не соответствует экзамену, за эти задачи вы набрали "
                    f"{primary_total} первичных баллов, что соответствует "
                    f"{secondary_score} вторичных баллов, процент успеха "
                    f"{success_percent_text}%."
                )
            else:
                exam_mismatch_notice = (
                    "Вариант не соответствует экзамену, за эти задачи вы набрали "
                    f"{primary_total} первичных баллов, процент успеха "
                    f"{success_percent_text}%."
                )

    context = {
        "active_tab": "tasks",
        "role": role,
        "assignment": assignment,
        "assignment_info": _build_assignment_context(assignment),
        "attempts": attempts,
        "exam_mismatch_notice": exam_mismatch_notice,
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
    """Teacher/students classes dashboard: list and create classes, show join links."""

    role = _get_dashboard_role(request)
    if role == "teacher" and not hasattr(request.user, "teacherprofile"):
        role = "student"

    if role == "teacher":
        if request.method == "POST":
            action = request.POST.get("action")
            if action == "create_class":
                name = (request.POST.get("name") or "").strip() or _("Новый класс")
                subject_id = request.POST.get("subject")
                study_class = StudyClass.objects.create(name=name, created_by=request.user)
                if subject_id:
                    try:
                        subject = Subject.objects.get(pk=int(subject_id))
                        ClassTeacherSubject.objects.get_or_create(
                            study_class=study_class, teacher=request.user, subject=subject
                        )
                    except (Subject.DoesNotExist, ValueError, TypeError):
                        pass
                messages.success(request, _("Класс создан"))
                return redirect("accounts:dashboard-classes")

        classes = (
            StudyClass.objects.filter(teacher_subjects__teacher=request.user)
            .distinct()
            .prefetch_related("student_memberships__student", "teacher_subjects__subject")
            .order_by("-created_at")
        )
    else:
        classes = (
            StudyClass.objects.filter(student_memberships__student=request.user)
            .distinct()
            .prefetch_related("teacher_subjects__subject")
            .order_by("-created_at")
        )

    context = {
        "active_tab": "classes",
        "role": role,
        "classes": classes,
        "subjects": Subject.objects.all().order_by("name"),
    }
    return render(request, "accounts/dashboard/classes.html", context)


@login_required
def dashboard_students(request):
    """Teacher view: list my students by subject and generate invites."""

    if not hasattr(request.user, "teacherprofile"):
        raise PermissionDenied("Only teachers can access this section")

    role = _get_dashboard_role(request)
    if role != "teacher":
        role = "teacher"
        request.session["dashboard_role"] = role

    if request.method == "POST":
        if request.POST.get("action") == "create_invite":
            try:
                subject_id = int(request.POST.get("subject") or 0)
            except (TypeError, ValueError):
                subject_id = 0
            if subject_id:
                try:
                    subject = Subject.objects.get(pk=subject_id)
                    invite = TeacherSubjectInvite.objects.create(
                        teacher=request.user, subject=subject
                    )
                    messages.success(
                        request,
                        _("Создан код приглашения: ") + invite.code,
                    )
                except Subject.DoesNotExist:
                    messages.error(request, _("Предмет не найден"))
            return redirect("accounts:dashboard-students")

    # Active links grouped by subject
    links = (
        TeacherStudentLink.objects.filter(teacher=request.user, status=TeacherStudentLink.Status.ACTIVE)
        .select_related("student", "subject")
        .order_by("subject__name", "student__username")
    )
    invites = (
        TeacherSubjectInvite.objects.filter(teacher=request.user, is_active=True)
        .select_related("subject")
        .order_by("-created_at")
    )

    grouped: dict[int, dict] = {}
    for link in links:
        data = grouped.setdefault(
            link.subject_id,
            {"subject": link.subject, "students": []},
        )
        data["students"].append(link.student)

    context = {
        "active_tab": "students",
        "role": role,
        "grouped_links": grouped,
        "invites": invites,
        "subjects": Subject.objects.all().order_by("name"),
    }
    return render(request, "accounts/dashboard/students.html", context)


@login_required
def join_teacher_with_code(request, code: str):
    """Student uses a code to link with a teacher on a subject."""

    try:
        invite = TeacherSubjectInvite.objects.select_related("teacher", "subject").get(
            code=code, is_active=True
        )
    except TeacherSubjectInvite.DoesNotExist:
        messages.error(request, _("Неверный или истекший код учителя"))
        return redirect("accounts:dashboard-settings")

    link, created = TeacherStudentLink.objects.get_or_create(
        teacher=invite.teacher,
        student=request.user,
        subject=invite.subject,
        defaults={"status": TeacherStudentLink.Status.ACTIVE},
    )
    if not created and link.status != TeacherStudentLink.Status.ACTIVE:
        link.status = TeacherStudentLink.Status.ACTIVE
        link.save(update_fields=["status", "updated_at"]) if hasattr(link, "updated_at") else link.save()

    invite.is_active = False
    invite.save(update_fields=["is_active", "updated_at"]) if hasattr(invite, "updated_at") else invite.save()

    messages.success(request, _("Учитель добавлен: ") + str(invite.teacher))
    return redirect("accounts:dashboard-settings")


@login_required
def join_class_with_code(request, code: str):
    """Join a class using its join code (from StudyClass)."""

    try:
        study_class = StudyClass.objects.get(join_code=code, is_active=True)
    except StudyClass.DoesNotExist:
        messages.error(request, _("Неверный или недействительный код класса"))
        return redirect("accounts:dashboard-settings")

    ClassStudentMembership.objects.get_or_create(
        study_class=study_class, student=request.user
    )
    messages.success(request, _("Вы присоединились к классу: ") + study_class.name)
    return redirect("accounts:dashboard-settings")


@login_required
def assignment_create(request):
    """Simple form for teachers to assign a variant template to students/classes."""

    if not hasattr(request.user, "teacherprofile"):
        raise PermissionDenied("Only teachers can access this section")

    role = _get_dashboard_role(request)
    if role != "teacher":
        role = "teacher"
        request.session["dashboard_role"] = role

    # Collect recipients
    links = (
        TeacherStudentLink.objects.filter(teacher=request.user, status=TeacherStudentLink.Status.ACTIVE)
        .select_related("student", "subject")
        .order_by("student__username")
    )
    classes = (
        StudyClass.objects.filter(teacher_subjects__teacher=request.user)
        .distinct()
        .order_by("name")
    )

    if request.method == "POST":
        template_id = request.POST.get("template")
        student_ids = request.POST.getlist("students")
        class_ids = request.POST.getlist("classes")
        deadline_str = (request.POST.get("deadline") or "").strip()
        deadline = None
        if deadline_str:
            try:
                # Expect ISO datetime (YYYY-MM-DDTHH:MM)
                from datetime import datetime

                deadline = datetime.fromisoformat(deadline_str)
            except Exception:  # pragma: no cover - defensive
                deadline = None

        try:
            template = VariantTemplate.objects.get(pk=int(template_id))
        except (VariantTemplate.DoesNotExist, TypeError, ValueError):
            messages.error(request, _("Выберите корректный шаблон варианта"))
            return redirect("accounts:assignment-create")

        # Build recipient set
        user_ids: set[int] = set()
        for sid in student_ids:
            try:
                user_ids.add(int(sid))
            except (TypeError, ValueError):
                continue
        for cid in class_ids:
            try:
                c = StudyClass.objects.get(pk=int(cid))
            except (StudyClass.DoesNotExist, TypeError, ValueError):
                continue
            for m in c.student_memberships.all():
                user_ids.add(m.student_id)

        # Create assignments
        created = 0
        for uid in user_ids:
            VariantAssignment.objects.get_or_create(
                template=template,
                user_id=uid,
                defaults={"deadline": deadline},
            )
            created += 1
        messages.success(request, _("Назначено заданий: ") + str(created))
        return redirect("accounts:dashboard")

    context = {
        "active_tab": "teachers",
        "role": role,
        "templates": VariantTemplate.objects.all().order_by("name"),
        "links": links,
        "classes": classes,
    }
    return render(request, "accounts/dashboard/assignment_create.html", context)


def _percent(numerator: int | float | None, denominator: int | float | None) -> int:
    if not denominator:
        return 0
    return int(round((float(numerator or 0) / float(denominator)) * 100))


def _period_since(request):
    period = (request.GET.get("period") or "30").strip().lower()
    valid_periods = {"7", "30", "90", "all"}
    if period not in valid_periods:
        period = "30"
    if period == "all":
        return period, None
    return period, timezone.now() - timedelta(days=int(period))


@login_required
def system_journal(request):
    """Staff-only learning activity journal across the whole system."""

    if not request.user.is_staff:
        raise PermissionDenied("Only staff can access the system journal")

    role = _get_dashboard_role(request)
    period, since = _period_since(request)
    now = timezone.now()
    active_cutoff = now - timedelta(minutes=10)

    attempt_filter = Q(is_valid_attempt=True)
    training_filter = Q()
    variant_filter = Q()
    if since is not None:
        attempt_filter &= Q(checked_at__gte=since) | Q(checked_at__isnull=True, created_at__gte=since)
        training_filter &= (
            Q(last_activity_at__gte=since)
            | Q(last_activity_at__isnull=True, started_at__gte=since)
            | Q(ended_at__gte=since)
        )
        variant_filter &= (
            Q(last_seen_at__gte=since)
            | Q(last_seen_at__isnull=True, started_at__gte=since)
            | Q(completed_at__gte=since)
        )

    attempts_qs = Attempt.objects.filter(attempt_filter)
    trainings_qs = TrainingSession.objects.filter(training_filter)
    variants_qs = VariantAttempt.objects.filter(variant_filter)
    variant_task_attempts_qs = VariantTaskAttempt.objects.filter(
        is_valid_attempt=True,
        attempt_number__gt=0,
    )
    if since is not None:
        variant_task_attempts_qs = variant_task_attempts_qs.filter(
            Q(checked_at__gte=since) | Q(checked_at__isnull=True, created_at__gte=since)
        )
    active_variant_attempts = VariantAttempt.objects.filter(
        completed_at__isnull=True,
        last_seen_at__gte=active_cutoff,
    )
    active_training_sessions = TrainingSession.objects.filter(
        status=TrainingSession.Status.ACTIVE,
        last_activity_at__gte=active_cutoff,
    )

    active_user_ids = set(active_variant_attempts.values_list("assignment__user_id", flat=True))
    active_user_ids.update(active_training_sessions.values_list("user_id", flat=True))

    activity_user_ids = set(attempts_qs.values_list("user_id", flat=True))
    activity_user_ids.update(trainings_qs.values_list("user_id", flat=True))
    activity_user_ids.update(variants_qs.values_list("assignment__user_id", flat=True))

    attempt_rows = {
        row["user_id"]: row
        for row in attempts_qs.values("user_id").annotate(
            attempts_total=Count("id"),
            attempts_correct=Count("id", filter=Q(is_correct=True)),
            last_attempt_at=Max("checked_at"),
        )
    }
    training_rows = {
        row["user_id"]: row
        for row in trainings_qs.values("user_id").annotate(
            training_sessions_total=Count("id", distinct=True),
            training_sessions_active=Count("id", filter=Q(status=TrainingSession.Status.ACTIVE), distinct=True),
            training_steps_total=Count("steps", filter=Q(steps__status=TrainingSessionStep.Status.ANSWERED)),
            training_steps_correct=Count("steps", filter=Q(steps__result=TrainingSessionStep.Result.CORRECT)),
            last_training_at=Max("last_activity_at"),
        )
    }
    variant_rows = {
        row["assignment__user_id"]: row
        for row in variants_qs.values("assignment__user_id").annotate(
            variant_attempts_total=Count("id"),
            variant_attempts_completed=Count("id", filter=Q(completed_at__isnull=False)),
            variant_attempts_active=Count("id", filter=Q(completed_at__isnull=True)),
            last_variant_at=Max("last_seen_at"),
        )
    }

    users = (
        get_user_model()
        .objects.filter(id__in=activity_user_ids)
        .order_by("username")
    )
    very_old = now - timedelta(days=36500)
    user_rows = []
    for user in users:
        attempt_data = attempt_rows.get(user.id, {})
        training_data = training_rows.get(user.id, {})
        variant_data = variant_rows.get(user.id, {})
        last_dates = [
            attempt_data.get("last_attempt_at"),
            training_data.get("last_training_at"),
            variant_data.get("last_variant_at"),
        ]
        last_activity_at = max([value for value in last_dates if value], default=None)
        attempts_total = int(attempt_data.get("attempts_total") or 0)
        attempts_correct = int(attempt_data.get("attempts_correct") or 0)
        training_steps_total = int(training_data.get("training_steps_total") or 0)
        training_steps_correct = int(training_data.get("training_steps_correct") or 0)
        total_answers = attempts_total + training_steps_total
        total_correct = attempts_correct + training_steps_correct
        user_rows.append(
            {
                "user": user,
                "is_active_now": user.id in active_user_ids,
                "last_activity_at": last_activity_at,
                "attempts_total": attempts_total,
                "training_sessions_total": int(training_data.get("training_sessions_total") or 0),
                "training_sessions_active": int(training_data.get("training_sessions_active") or 0),
                "variant_attempts_total": int(variant_data.get("variant_attempts_total") or 0),
                "variant_attempts_completed": int(variant_data.get("variant_attempts_completed") or 0),
                "variant_attempts_active": int(variant_data.get("variant_attempts_active") or 0),
                "accuracy_percent": _percent(total_correct, total_answers),
            }
        )
    user_rows.sort(
        key=lambda row: (
            row["is_active_now"],
            row["last_activity_at"] or very_old,
        ),
        reverse=True,
    )

    top_task_stats = list(
        attempts_qs.values("task_id")
        .annotate(
            period_attempts=Count("id"),
            period_correct=Count("id", filter=Q(is_correct=True)),
            period_users=Count("user_id", distinct=True),
        )
        .order_by("-period_attempts")[:20]
    )
    top_task_ids = [row["task_id"] for row in top_task_stats if row["task_id"]]
    top_task_map = {
        task.id: task
        for task in Task.objects.select_related("subject", "exam_version", "type").filter(id__in=top_task_ids)
    }
    top_tasks = []
    for stats in top_task_stats:
        task = top_task_map.get(stats["task_id"])
        if task is None:
            continue
        task.period_attempts = int(stats["period_attempts"] or 0)
        task.period_correct = int(stats["period_correct"] or 0)
        task.period_users = int(stats["period_users"] or 0)
        top_tasks.append(task)
    for task in top_tasks:
        task.period_success_percent = _percent(task.period_correct, task.period_attempts)
        task.all_time_success_percent = _percent(
            float(task.score_norm_sum_total or 0.0),
            int(task.attempts_total or 0),
        )
        task.avg_time_minutes = (
            round(float(task.time_spent_avg_seconds or 0.0) / 60.0, 1)
            if task.time_spent_avg_seconds
            else None
        )

    problem_tasks = [
        task
        for task in top_tasks
        if task.period_attempts >= 3
    ]
    problem_tasks.sort(
        key=lambda task: (
            task.period_success_percent,
            -(task.time_spent_avg_seconds or 0),
            -task.period_attempts,
        )
    )
    problem_tasks = problem_tasks[:10]

    recent_attempts = [
        {
            "kind": "task",
            "at": attempt.checked_at or attempt.created_at,
            "user": attempt.user,
            "title": attempt.task.title,
            "meta": attempt.task.type.name if attempt.task.type_id else "",
            "result": "верно" if attempt.is_correct else "ошибка",
        }
        for attempt in attempts_qs.select_related("user", "task", "task__type")
        .order_by("-checked_at", "-created_at")[:15]
    ]
    recent_trainings = [
        {
            "kind": "training",
            "at": session.last_activity_at or session.ended_at or session.started_at,
            "user": session.user,
            "title": session.exam_version.name,
            "meta": session.exam_version.subject.name,
            "result": session.get_status_display(),
        }
        for session in trainings_qs.select_related("user", "exam_version", "exam_version__subject")
        .order_by("-last_activity_at", "-started_at")[:10]
    ]
    recent_variants = [
        {
            "kind": "variant",
            "at": attempt.last_seen_at or attempt.completed_at or attempt.started_at,
            "user": attempt.assignment.user,
            "title": attempt.assignment.template.name,
            "meta": f"попытка {attempt.attempt_number}",
            "result": "завершён" if attempt.completed_at else "в работе",
        }
        for attempt in variants_qs.select_related("assignment__user", "assignment__template")
        .order_by("-last_seen_at", "-started_at")[:10]
    ]
    recent_activity = recent_attempts + recent_trainings + recent_variants
    recent_activity.sort(key=lambda entry: entry["at"] or very_old, reverse=True)
    recent_activity = recent_activity[:25]

    summary = {
        "users_with_activity": len(activity_user_ids),
        "active_now": len(active_user_ids),
        "task_attempts": attempts_qs.count(),
        "training_sessions": trainings_qs.count(),
        "variant_attempts": variants_qs.count(),
        "variant_task_attempts": variant_task_attempts_qs.count(),
        "completed_variants": variants_qs.filter(completed_at__isnull=False).count(),
        "task_accuracy_percent": _percent(
            attempts_qs.filter(is_correct=True).count(),
            attempts_qs.count(),
        ),
    }

    context = {
        "active_tab": "system_journal",
        "role": role,
        "period": period,
        "period_options": [
            ("7", "7 дней"),
            ("30", "30 дней"),
            ("90", "90 дней"),
            ("all", "всё время"),
        ],
        "summary": summary,
        "user_rows": user_rows[:100],
        "top_tasks": top_tasks,
        "problem_tasks": problem_tasks,
        "recent_activity": recent_activity,
    }
    return render(request, "accounts/dashboard/system_journal.html", context)


@login_required
def dashboard_methodist(request):
    """Methodist dashboard: create/edit courses and theory cards."""

    if not hasattr(request.user, "methodistprofile"):
        raise PermissionDenied("Only methodists can access this section")

    role = _get_dashboard_role(request)
    if role != "methodist":
        role = "methodist"
        request.session["dashboard_role"] = role

    course_form = CourseForm()
    theory_form = CourseTheoryCardForm()

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_course":
            course_form = CourseForm(request.POST)
            if course_form.is_valid():
                course_form.save()
                messages.success(request, _("Курс создан"))
                return redirect("accounts:dashboard-methodist")
        elif action == "create_theory":
            theory_form = CourseTheoryCardForm(request.POST)
            if theory_form.is_valid():
                theory_form.save()
                messages.success(request, _("Теоретическая карточка создана"))
                return redirect("accounts:dashboard-methodist")

    # Lists
    from courses.models import Course, CourseTheoryCard

    courses = Course.objects.order_by("title")
    theory_cards = CourseTheoryCard.objects.select_related("course").order_by(
        "course__title", "slug"
    )

    context = {
        "active_tab": "methodist",
        "role": role,
        "course_form": course_form,
        "theory_form": theory_form,
        "courses": courses,
        "theory_cards": theory_cards,
    }
    return render(request, "accounts/dashboard/methodist.html", context)


@login_required
def dashboard_settings(request):
    role = _get_dashboard_role(request)

    if request.method == "POST":
        user_submit = "user_submit" in request.POST
        password_submit = "password_submit" in request.POST
        role_submit = "role_submit" in request.POST
        action = request.POST.get("action")

        if action == "join_teacher_code":
            code = (request.POST.get("code") or "").strip()
            if code:
                return join_teacher_with_code(request, code)
        elif action == "join_class_code":
            code = (request.POST.get("code") or "").strip()
            if code:
                return join_class_with_code(request, code)
        elif action == "leave_teacher":
            try:
                link_id = int(request.POST.get("link_id") or 0)
            except (TypeError, ValueError):
                link_id = 0
            if link_id:
                TeacherStudentLink.objects.filter(id=link_id, student=request.user).update(
                    status=TeacherStudentLink.Status.REVOKED
                )
                messages.success(request, _("Вы отказались от учителя"))
            return redirect("accounts:dashboard-settings")
        elif action == "leave_class":
            try:
                membership_id = int(request.POST.get("membership_id") or 0)
            except (TypeError, ValueError):
                membership_id = 0
            if membership_id:
                ClassStudentMembership.objects.filter(id=membership_id, student=request.user).delete()
                messages.success(request, _("Вы вышли из класса"))
            return redirect("accounts:dashboard-settings")

        if user_submit:
            u_form = UserUpdateForm(request.POST, instance=request.user)
            p_form = PasswordChangeForm(request.user)
            if u_form.is_valid():
                u_form.save()
                return redirect("accounts:dashboard-settings")
        elif password_submit:
            u_form = UserUpdateForm(instance=request.user)
            p_form = PasswordChangeForm(request.user, request.POST)
            if p_form.is_valid():
                user = p_form.save()
                update_session_auth_hash(request, user)
                return redirect("accounts:dashboard-settings")
        elif role_submit:
            new_role = request.POST.get("role")
            if new_role in {"student", "teacher", "methodist"}:
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
        "my_teacher_links": TeacherStudentLink.objects.filter(
            student=request.user, status=TeacherStudentLink.Status.ACTIVE
        ).select_related("teacher", "subject"),
        "my_class_memberships": ClassStudentMembership.objects.filter(
            student=request.user
        ).select_related("study_class"),
    }
    return render(request, "accounts/dashboard/settings.html", context)

@login_required
def dashboard_courses(request):
    """Display all courses the current user is enrolled in."""

    role = _get_dashboard_role(request)

    enrollments_qs = (
        request.user.course_enrollments.select_related("course")
        .prefetch_related(
            Prefetch(
                "course__modules",
                queryset=CourseModule.objects.order_by("col", "rank", "id").prefetch_related(
                    Prefetch(
                        "items",
                        queryset=CourseModuleItem.objects.select_related("theory_card", "task")
                        .order_by("position", "id"),
                    )
                ),
            ),
            Prefetch(
                "course__graph_edges",
                queryset=CourseGraphEdge.objects.select_related("src", "dst"),
            ),
        )
        .order_by("-enrolled_at")
    )

    enrollments = []
    for enrollment in enrollments_qs:
        course = enrollment.course

        modules = list(course.modules.all())
        course_task_type_ids = {
            module.task_type_id
            for module in modules
            if module.kind == CourseModule.Kind.TASK_TYPE and module.task_type_id
        }
        course_type_progress_map = (
            build_type_progress_map(user=request.user, task_type_ids=course_task_type_ids)
            if course_task_type_ids
            else {}
        )
        progress_map = build_module_progress_map(
            user=request.user,
            enrollment=enrollment,
            modules=modules,
            type_progress_map=course_type_progress_map,
        )

        incoming_edges_by_dst: dict[int, list[CourseGraphEdge]] = defaultdict(list)
        for edge in course.graph_edges.all():
            incoming_edges_by_dst[edge.dst_id].append(edge)

        locked_by_module: dict[int, bool] = {}
        nodes = []
        for module in modules:
            module_progress = progress_map.get(module.id, 0.0)
            unlocked = is_module_unlocked_for_user(
                user=request.user,
                module=module,
                enrollment=enrollment,
                incoming_edges=incoming_edges_by_dst.get(module.id, []),
                progress_map=progress_map,
                type_progress_map=course_type_progress_map,
            )
            locked_by_module[module.id] = not unlocked

            nodes.append(
                {
                    "id": module.id,
                    "slug": module.slug,
                    "title": module.title,
                    "subtitle": module.subtitle,
                    "col": module.col,
                    "row": module.rank,
                    "dx": module.dx,
                    "dy": module.dy,
                    "locked": locked_by_module[module.id],
                    "kind": module.kind,
                    "progress": max(0.0, min(100.0, module_progress)),
                    "url": module.get_absolute_url() if hasattr(module, "get_absolute_url") else "",
                }
            )

        edges = []
        for edge in course.graph_edges.all():
            src_progress = progress_map.get(edge.src_id, 0.0)
            edge_unlocked_by_progress = src_progress >= MODULE_UNLOCK_PROGRESS_THRESHOLD
            src_locked = locked_by_module.get(edge.src_id, False)
            dst_locked = locked_by_module.get(edge.dst_id, False)
            edge_locked = (
                not edge_unlocked_by_progress
                and (edge.is_locked or src_locked or dst_locked)
            )

            edges.append(
                {
                    "id": edge.id,
                    "src": edge.src_id,
                    "dst": edge.dst_id,
                    "kind": edge.kind,
                    "weight": float(edge.weight),
                    "locked": edge_locked,
                }
            )

        enrollment.graph = {"nodes": nodes, "edges": edges}
        enrollments.append(enrollment)

    context = {
        "active_tab": "courses",
        "role": role,
        "enrollments": enrollments,
    }
    return render(request, "accounts/dashboard/courses.html", context)


def _get_variant_basket(request) -> dict:
    basket = request.session.get(SESSION_KEY) or {}
    tasks = basket.get("tasks") or []
    if not isinstance(tasks, list):
        tasks = []
    return {
        "tasks": list(tasks),
        "time_limit": basket.get("time_limit") or "",
        "deadline": basket.get("deadline") or "",
    }


def _save_variant_basket(request, *, tasks: list[int], time_limit: str = "", deadline: str = "") -> None:
    request.session[SESSION_KEY] = {
        "tasks": tasks,
        "time_limit": time_limit.strip() if isinstance(time_limit, str) else "",
        "deadline": deadline.strip() if isinstance(deadline, str) else "",
    }
    request.session.modified = True


def _parse_time_limit(value: str) -> timedelta | None:
    """Convert HH:MM or minutes string to ``timedelta``."""

    value = (value or "").strip()
    if not value:
        return None

    try:
        if ":" in value:
            parts = value.split(":")
            if len(parts) == 2:
                hours, minutes = parts
                seconds = 0
            elif len(parts) == 3:
                hours, minutes, seconds = parts
            else:
                return None
            hours_i = int(hours)
            minutes_i = int(minutes)
            seconds_i = int(seconds)
        else:
            hours_i = 0
            minutes_i = int(value)
            seconds_i = 0
        if hours_i < 0 or minutes_i < 0 or seconds_i < 0:
            return None
    except ValueError:
        return None

    return timedelta(hours=hours_i, minutes=minutes_i, seconds=seconds_i)


def _generate_template_name(user, tasks_count: int) -> str:
    """Build a unique template name for the saved basket."""

    username = getattr(user, "username", "")
    timestamp = timezone.localtime().strftime("%Y-%m-%d %H:%M")
    base = f"Вариант {username} {timestamp}".strip()
    if tasks_count:
        base = f"{base} • {tasks_count} задач"

    candidate = base
    suffix = 2
    while VariantTemplate.objects.filter(name=candidate).exists():
        candidate = f"{base} #{suffix}"
        suffix += 1
    return candidate


@login_required
def variant_attempt_work(request, attempt_id: int):
    """Compatibility redirect for the retired server-rendered attempt page."""

    try:
        attempt = variant_services.get_attempt_with_prefetch(request.user, attempt_id)
    except drf_exceptions.NotFound as exc:
        logger.warning("Attempt not found", extra={"attempt_id": attempt_id}, exc_info=exc)
        raise Http404("Not found") from exc
    return redirect("accounts:variant-attempt-solver", attempt_id=attempt.id)


@login_required
def variant_attempt_solver(request, attempt_id: int):
    """Interactive solver UI with per-task timers driven by API endpoints."""

    role = _get_dashboard_role(request)
    try:
        attempt = variant_services.get_attempt_with_prefetch(request.user, attempt_id)
    except drf_exceptions.NotFound as exc:
        logger.warning("Attempt not found", extra={"attempt_id": attempt_id}, exc_info=exc)
        raise Http404("Not found") from exc

    assignment = attempt.assignment
    time_left_delta = variant_services.get_time_left(attempt)
    time_left = _format_duration(time_left_delta) if time_left_delta else None
    exam_version = assignment.template.exam_version
    start_info = exam_version.start_info if exam_version else ""

    attempts_left = variant_services.get_attempts_left(assignment)
    deadline_passed = bool(assignment.deadline and assignment.deadline < timezone.now())
    can_restart = (not deadline_passed) and (attempts_left is None or attempts_left > 0)

    context = {
        "active_tab": "tasks",
        "role": role,
        "attempt_id": attempt.id,
        "assignment": assignment,
        "attempt": attempt,
        "time_left": time_left,
        "exam_start_info": start_info,
        "solver_meta": {
            "assignment_id": assignment.id,
            "can_restart": can_restart,
            "attempts_left": attempts_left,
            "solver_url_template": reverse(
                "accounts:variant-attempt-solver",
                kwargs={"attempt_id": 0},
            ),
        },
    }
    return render(request, "accounts/dashboard/variant_attempt_solver.html", context)





@login_required
def variant_basket_edit(request):
    """Allow teachers to review and configure tasks stored in the basket."""

    role = _get_dashboard_role(request)
    basket = _get_variant_basket(request)

    task_ids = [task_id for task_id in basket["tasks"] if isinstance(task_id, int)]
    tasks_map = {
        task.id: task
        for task in Task.objects.filter(id__in=task_ids).select_related("subject", "type")
    }
    ordered_tasks = [tasks_map[task_id] for task_id in task_ids if task_id in tasks_map]

    if request.method == "POST":
        action = request.POST.get("action") or ""
        time_limit = request.POST.get("time_limit", basket["time_limit"])
        deadline = request.POST.get("deadline", basket["deadline"])

        if action == "reset":
            _save_variant_basket(request, tasks=[], time_limit="", deadline="")
            messages.success(request, _("Корзина варианта очищена."))
            return redirect("accounts:variant-basket-edit")

        if action == "save":
            parsed_time_limit = _parse_time_limit(time_limit)
            if time_limit.strip() and parsed_time_limit is None:
                messages.error(
                    request,
                    _("Введите таймер в формате HH:MM или количество минут."),
                )
                return redirect("accounts:variant-basket-edit")

            if not ordered_tasks:
                messages.error(request, _("Добавьте хотя бы одну задачу в вариант."))
                return redirect("accounts:variant-basket-edit")

            with transaction.atomic():
                template = VariantTemplate.objects.create(
                    name=_generate_template_name(request.user, len(ordered_tasks)),
                    time_limit=parsed_time_limit,
                )
                for order, task in enumerate(ordered_tasks, start=1):
                    VariantTask.objects.create(
                        template=template,
                        task=task,
                        order=order,
                    )

            _save_variant_basket(
                request,
                tasks=[],
                time_limit=time_limit,
                deadline=deadline,
            )
            messages.success(
                request,
                _("Вариант сохранён как «%(name)s».") % {"name": template.name},
            )
            return redirect("accounts:variant-basket-edit")

        _save_variant_basket(
            request,
            tasks=basket["tasks"],
            time_limit=time_limit,
            deadline=deadline,
        )
        if action == "continue":
            messages.success(request, _("Настройки сохранены, можно продолжать собирать вариант."))
        else:
            messages.success(request, _("Настройки варианта обновлены."))
        return redirect("accounts:variant-basket-edit")

    context = {
        "active_tab": "tasks",
        "role": role,
        "basket": basket,
        "basket_tasks": ordered_tasks,
    }
    return render(request, "accounts/dashboard/variant_basket_edit.html", context)


@login_required
def variant_basket_add(request):
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"

    def _ajax_response(payload: dict, status: int = 200):
        if is_ajax:
            return JsonResponse(payload, status=status)
        return None

    if request.method != "POST":
        response = _ajax_response({"ok": False, "error": "Метод не поддерживается"}, status=405)
        return response or redirect("accounts:variant-basket-edit")

    if not hasattr(request.user, "teacherprofile"):
        message = _("У вас нет прав для работы с вариантом.")
        response = _ajax_response({"ok": False, "error": str(message)}, status=403)
        if response:
            return response
        messages.error(request, message)
        return redirect("accounts:variant-basket-edit")

    try:
        task_id = int(request.POST.get("task_id", ""))
    except (TypeError, ValueError):
        message = _("Некорректный идентификатор задания.")
        response = _ajax_response({"ok": False, "error": str(message)}, status=400)
        if response:
            return response
        messages.error(request, message)
        return redirect("accounts:variant-basket-edit")

    try:
        Task.objects.get(pk=task_id)
    except Task.DoesNotExist:
        message = _("Задача не найдена.")
        response = _ajax_response({"ok": False, "error": str(message)}, status=404)
        if response:
            return response
        messages.error(request, message)
        return redirect("accounts:variant-basket-edit")

    basket = _get_variant_basket(request)
    if task_id not in basket["tasks"]:
        basket["tasks"].append(task_id)
        _save_variant_basket(
            request,
            tasks=basket["tasks"],
            time_limit=basket["time_limit"],
            deadline=basket["deadline"],
        )
        message = _("Задача добавлена в вариант.")
        response = _ajax_response(
            {"ok": True, "count": len(basket["tasks"]), "task_id": task_id},
        )
        if response:
            return response
        messages.success(request, message)
        return redirect("accounts:variant-basket-edit")

    response = _ajax_response(
        {"ok": True, "count": len(basket["tasks"]), "task_id": task_id, "already_added": True},
    )
    if response:
        return response
    messages.info(request, _("Эта задача уже есть в варианте."))
    return redirect("accounts:variant-basket-edit")


@login_required
def variant_basket_remove(request):
    if request.method != "POST":
        return redirect("accounts:variant-basket-edit")

    try:
        task_id = int(request.POST.get("task_id", ""))
    except (TypeError, ValueError):
        messages.error(request, _("Некорректный идентификатор задания."))
        return redirect("accounts:variant-basket-edit")

    basket = _get_variant_basket(request)
    if task_id in basket["tasks"]:
        basket["tasks"].remove(task_id)
        _save_variant_basket(
            request,
            tasks=basket["tasks"],
            time_limit=basket["time_limit"],
            deadline=basket["deadline"],
        )
        messages.success(request, _("Задача удалена из варианта."))

    return redirect("accounts:variant-basket-edit")


@login_required
def variant_basket_reset(request):
    _save_variant_basket(request, tasks=[], time_limit="", deadline="")
    messages.success(request, _("Корзина варианта очищена."))
    return redirect("accounts:variant-basket-edit")





