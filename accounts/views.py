import logging
import json
from collections import defaultdict
from collections.abc import Mapping
from copy import deepcopy
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.db.models import Prefetch
from django.http import Http404, JsonResponse
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
    VariantTemplate,
    VariantAssignment,
    VariantTask,
)
from apps.recsys.forms import TaskAnswerForm
from apps.recsys.service_utils import variants as variant_services
from apps.recsys.service_utils.type_progress import (
    TypeProgressInfo,
    build_type_progress_map,
)
from subjects.models import Subject
from courses.models import CourseGraphEdge, CourseModule, CourseModuleItem
from .context_processors import SESSION_KEY
from courses.services import (
    MODULE_UNLOCK_PROGRESS_THRESHOLD,
    build_module_progress_map,
    is_module_unlocked_for_user,
)

from .forms import (
    PasswordChangeForm,
    SignupForm,
    TaskCreateForm,
    UserUpdateForm,
    build_task_skill_formset,
    CourseForm,
    CourseTheoryCardForm,
)
from .forms_exams import ExamPreferencesForm
from .models import (
    StudentProfile,
    StudyClass,
    ClassStudentMembership,
    ClassTeacherSubject,
    TeacherStudentLink,
    TeacherSubjectInvite,
    teacher_has_subject_access,
)


logger = logging.getLogger("accounts")


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
    profile, _created = StudentProfile.objects.get_or_create(user=request.user)
    subjects_qs = Subject.objects.all().prefetch_related("exam_versions").order_by("name")

    if request.method == "POST":
        form_type = request.POST.get("form_type")
        user_submit = "user_submit" in request.POST
        password_submit = "password_submit" in request.POST
        role_submit = "role_submit" in request.POST
        exams_submit = "exams_submit" in request.POST
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
            if new_role in {"student", "teacher", "methodist"}:
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
        # Settings: teacher/student/class relations
        "my_teacher_links": TeacherStudentLink.objects.filter(
            student=request.user, status=TeacherStudentLink.Status.ACTIVE
        ).select_related("teacher", "subject"),
        "my_class_memberships": ClassStudentMembership.objects.filter(
            student=request.user
        ).select_related("study_class"),
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

    mastery_by_skill_id: dict[int, float] = {
        sm.skill_id: float(sm.mastery) for sm in skill_masteries
    }

    exam_ids = {exam.id for exam in selected_exams}

    types_by_exam: dict[int, list[TaskType]] = {}
    if exam_ids:
        task_types = (
            TaskType.objects.filter(exam_version_id__in=exam_ids)
            .select_related("subject", "exam_version")
            .order_by("exam_version__name", "display_order", "name")
        )
        for task_type in task_types:
            if task_type.exam_version_id is None:
                continue
            types_by_exam.setdefault(task_type.exam_version_id, []).append(task_type)

    all_task_type_ids: set[int] = {
        task_type.id for task_types in types_by_exam.values() for task_type in task_types
    }
    default_progress = TypeProgressInfo(
        raw_mastery=0.0,
        effective_mastery=0.0,
        coverage_ratio=0.0,
        required_count=0,
        covered_count=0,
        required_tags=tuple(),
        covered_tag_ids=frozenset(),
        tag_progress=tuple(),
    )
    type_progress_map = (
        build_type_progress_map(user=request.user, task_type_ids=all_task_type_ids)
        if all_task_type_ids
        else {}
    )

    def get_progress_for_type(type_id: int) -> TypeProgressInfo:
        return type_progress_map.get(type_id, default_progress)

    exam_statistics = []
    for exam in selected_exams:
        types = types_by_exam.get(exam.id, [])
        type_progress = {t.id: get_progress_for_type(t.id) for t in types}
        effective_masteries = {type_id: info.effective_mastery for type_id, info in type_progress.items()}
        exam_statistics.append(
            {
                "subject": exam.subject,
                "exam_version": exam,
                "groups": list(exam.skill_groups.all()),
                "types": types,
                "skill_masteries": mastery_by_skill_id,
                "type_masteries": effective_masteries,
                "type_progress": type_progress,
            }
        )

    context = {
        "active_tab": "statistics",
        "role": role,
        "exam_statistics": exam_statistics,
        # Settings page additions
        "my_teacher_links": TeacherStudentLink.objects.filter(
            student=request.user, status=TeacherStudentLink.Status.ACTIVE
        ).select_related("teacher", "subject"),
        "my_class_memberships": ClassStudentMembership.objects.filter(
            student=request.user
        ).select_related("study_class"),
    }
    return render(request, "accounts/dashboard/subjects.html", context)


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
    """Allow students to work on a specific attempt."""

    role = _get_dashboard_role(request)
    try:
        attempt = variant_services.get_attempt_with_prefetch(request.user, attempt_id)
    except drf_exceptions.NotFound as exc:
        raise Http404(str(exc)) from exc

    assignment = attempt.assignment
    template_tasks = {
        task.id: task
        for task in assignment.template.template_tasks.select_related("task__subject", "task__type", "task").all()
    }
    tasks_progress = variant_services.build_tasks_progress(attempt)

    invalid_form: TaskAnswerForm | None = None
    invalid_task_id: int | None = None

    if request.method == "POST":
        action = request.POST.get("action") or ""
        if action == "save-task":
            variant_task_id_raw = request.POST.get("variant_task_id")
            try:
                variant_task_id = int(variant_task_id_raw or "")
            except (TypeError, ValueError):
                messages.error(request, _("Не удалось определить задачу."))
            else:
                progress_entry = next(
                    (entry for entry in tasks_progress if entry["variant_task_id"] == variant_task_id),
                    None,
                )
                variant_task = template_tasks.get(variant_task_id)
                if not progress_entry or not variant_task or not variant_task.task:
                    messages.error(request, _("Задача недоступна."))
                else:
                    snapshot = progress_entry.get("task_snapshot") or {}
                    correct_answer = None
                    if isinstance(snapshot, dict):
                        correct_answer = snapshot.get("correct_answer")
                    if correct_answer is None:
                        correct_answer = deepcopy(variant_task.task.correct_answer or {})
                    saved_answer = progress_entry.get("saved_response")
                    form = TaskAnswerForm(
                        correct_answer,
                        data=request.POST,
                        initial_answer=saved_answer,
                    )
                    if not form.is_available:
                        messages.error(request, _("Для этой задачи пока нет формы ответа."))
                    elif form.is_valid():
                        try:
                            variant_services.save_task_response(
                                request.user,
                                attempt_id=attempt_id,
                                variant_task_id=variant_task_id,
                                answer=form.get_answer(),
                            )
                        except drf_exceptions.ValidationError as exc:
                            messages.error(request, _format_error_detail(exc.detail))
                        except drf_exceptions.APIException as exc:
                            detail = getattr(exc, "detail", str(exc))
                            messages.error(request, _format_error_detail(detail))
                        except drf_exceptions.NotFound as exc:
                            raise Http404(str(exc)) from exc
                        else:
                            messages.success(request, _("Ответ сохранен."))
                            return redirect("accounts:variant-attempt-work", attempt_id=attempt_id)
                    else:
                        invalid_form = form
                        invalid_task_id = variant_task_id
        elif action == "finalize":
            try:
                variant_services.finalize_attempt(request.user, attempt_id)
            except drf_exceptions.ValidationError as exc:
                messages.error(request, _format_error_detail(exc.detail))
            except drf_exceptions.NotFound as exc:
                raise Http404(str(exc)) from exc
            else:
                messages.success(request, _("Попытка завершена."))
            return redirect("accounts:variant-attempt-work", attempt_id=attempt_id)

        attempt = variant_services.get_attempt_with_prefetch(request.user, attempt_id)
        assignment = attempt.assignment
        template_tasks = {
            task.id: task
            for task in assignment.template.template_tasks.select_related("task__subject", "task__type", "task").all()
        }
        tasks_progress = variant_services.build_tasks_progress(attempt)

    tasks = []
    for item in tasks_progress:
        variant_task = template_tasks.get(item["variant_task_id"])
        if not variant_task:
            continue
        task = variant_task.task
        snapshot = item.get("task_snapshot") or {}
        task_payload = snapshot if isinstance(snapshot, dict) else {}
        display = {
            "title": (
                task_payload.get("title")
                or task_payload.get("content", {}).get("title")
                or getattr(task, "title", "")
            ),
            "description": (
                task_payload.get("description")
                or task_payload.get("content", {}).get("statement")
                or ""
            ),
            "rendering_strategy": task_payload.get("rendering_strategy") or getattr(task, "rendering_strategy", None),
            "image": task_payload.get("image") or (task.image.url if getattr(task, "image", None) else None),
        }

        saved_response = item.get("saved_response")
        saved_response_display = _stringify_response(saved_response)
        saved_response_updated_at = item.get("saved_response_updated_at")

        correct_answer_meta = None
        if isinstance(task_payload, dict):
            correct_answer_meta = task_payload.get("correct_answer")
        if correct_answer_meta is None and task is not None:
            correct_answer_meta = deepcopy(task.correct_answer or {})
        else:
            correct_answer_meta = deepcopy(correct_answer_meta or {})

        if invalid_form is not None and invalid_task_id == variant_task.id:
            form = invalid_form
        else:
            form = TaskAnswerForm(correct_answer_meta, initial_answer=saved_response)

        attempts_history = []
        for attempt_entry in item.get("attempts", []):
            payload = attempt_entry.task_snapshot or {}
            response_payload = {}
            if isinstance(payload, dict):
                response_payload = payload.get("response") or {}
            response_value = None
            if isinstance(response_payload, Mapping):
                response_value = response_payload.get("value")
                if response_value is None:
                    response_value = response_payload.get("answer")
                if response_value is None:
                    response_value = response_payload.get("text")
            elif response_payload is not None:
                response_value = response_payload

            attempts_history.append(
                {
                    "number": attempt_entry.attempt_number,
                    "is_correct": attempt_entry.is_correct,
                    "created_at": attempt_entry.created_at,
                    "response_text": _stringify_response(response_value),
                }
            )

        max_attempts = item.get("max_attempts")
        attempts_used = item.get("attempts_used") or 0
        remaining_attempts = None
        if max_attempts is not None:
            remaining_attempts = max(0, max_attempts - attempts_used)

        tasks.append(
            {
                "variant_task": variant_task,
                "task": task,
                "order": item.get("order"),
                "display": display,
                "task_body_html": item.get("task_body_html"),
                "task_rendering_strategy": item.get("task_rendering_strategy"),
                "skills": list(task.skills.all()) if task else [],
                "is_completed": item.get("is_completed", False),
                "remaining_attempts": remaining_attempts,
                "max_attempts": max_attempts,
                "history": attempts_history,
                "last_attempt": attempts_history[-1] if attempts_history else None,
                "form": form,
                "form_available": form.is_available,
                "saved_response_display": saved_response_display,
                "saved_response_updated_at": saved_response_updated_at,
                "has_saved_response": saved_response is not None,
            }
        )

    tasks.sort(key=lambda entry: entry["order"] or 0)

    attempt_completed = attempt.completed_at is not None
    progress_summary = variant_services.calculate_assignment_progress(assignment)
    all_completed = all(entry["is_completed"] for entry in tasks)
    all_answers_saved = all(entry["has_saved_response"] for entry in tasks)
    time_left_delta = variant_services.get_time_left(attempt)
    time_left = _format_duration(time_left_delta) if time_left_delta else None

    context = {
        "active_tab": "tasks",
        "role": role,
        "assignment": assignment,
        "attempt": attempt,
        "tasks": tasks,
        "progress_summary": progress_summary,
        "attempt_completed": attempt_completed,
        "all_completed": all_completed,
        "all_answers_saved": all_answers_saved,
        "time_left": time_left,
        "task_answer_submit_label": _("Сохранить ответ"),
        "task_answer_legend": _("Ответ на задание"),
        "task_answer_unavailable_message": _("Для этого задания пока нет формы ответа."),
    }
    return render(request, "accounts/dashboard/variant_attempt_work.html", context)


@login_required
def variant_attempt_solver(request, attempt_id: int):
    """Interactive solver UI with per-task timers driven by API endpoints."""

    role = _get_dashboard_role(request)
    try:
        attempt = variant_services.get_attempt_with_prefetch(request.user, attempt_id)
    except drf_exceptions.NotFound as exc:
        raise Http404(str(exc)) from exc

    assignment = attempt.assignment
    time_left_delta = variant_services.get_time_left(attempt)
    time_left = _format_duration(time_left_delta) if time_left_delta else None
    exam_version = assignment.template.exam_version
    start_info = exam_version.start_info if exam_version else ""

    context = {
        "active_tab": "tasks",
        "role": role,
        "attempt_id": attempt.id,
        "assignment": assignment,
        "attempt": attempt,
        "time_left": time_left,
        "exam_start_info": start_info,
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





