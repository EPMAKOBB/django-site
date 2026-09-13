from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import TeacherStudentLink

from .forms import StudentLessonDefaultsForm, StudentRecordForm, StudentSubjectForm
from .models import StudentRecord
from .services import accept_account_invite, create_account_invite


def _teacher_can_manage(user, student: StudentRecord) -> bool:
    return user.is_staff or TeacherStudentLink.objects.filter(
        teacher=user,
        student_record=student,
    ).exists()


@login_required
def student_edit(request, public_id):
    student = get_object_or_404(StudentRecord, public_id=public_id)
    if not _teacher_can_manage(request.user, student):
        raise PermissionDenied("Нет доступа к карточке ученика.")
    action = request.POST.get("action", "edit_student")
    subject_links = list(TeacherStudentLink.objects.filter(
        teacher=request.user, student_record=student,
    ).select_related("subject").order_by("subject__name"))
    editing_defaults = request.method == "POST" and action == "edit_lesson_defaults"
    if editing_defaults and request.POST.get("link_id") not in {str(link.pk) for link in subject_links}:
        raise PermissionDenied("Нет доступа к условиям занятий по этому предмету.")
    for link in subject_links:
        selected = editing_defaults and request.POST.get("link_id") == str(link.pk)
        link.defaults_form = StudentLessonDefaultsForm(
            request.POST if selected else None, instance=link, prefix=f"terms-{link.pk}",
        )
        if selected and link.defaults_form.is_valid():
            link.defaults_form.save()
            messages.success(request, f"Условия новых уроков по предмету «{link.subject.name}» сохранены.")
            return redirect(reverse("students:edit", args=[student.public_id]) + "#student-subjects")
    form = StudentRecordForm(
        request.POST if request.method == "POST" and action == "edit_student" else None,
        instance=student, actor=request.user,
    )
    subject_form = StudentSubjectForm(
        request.POST if request.method == "POST" and action == "add_subject" else None,
        teacher=request.user, student=student,
    )
    if request.method == "POST" and action == "add_subject" and subject_form.is_valid():
        try:
            link = subject_form.save()
        except ValidationError as exc:
            subject_form.add_error(None, exc)
        else:
            messages.success(request, f"Предмет «{link.subject.name}» добавлен. Теперь можно планировать уроки по нему.")
            return redirect(reverse("students:edit", args=[student.public_id]) + "#student-subjects")
    if request.method == "POST" and action == "edit_student" and form.is_valid():
        form.save()
        messages.success(request, "Карточка ученика обновлена.")
        return redirect("students:edit", public_id=student.public_id)
    return render(
        request,
        "students/student_edit.html",
        {
            "form": form,
            "student": student,
            "subject_form": subject_form,
            "subject_links": subject_links,
            "active_tab": "students",
            "role": "teacher",
            "invite_url": request.session.pop("student_invite_url", ""),
        },
    )


@require_POST
@login_required
def account_invite_create(request, public_id):
    student = get_object_or_404(StudentRecord, public_id=public_id)
    if not _teacher_can_manage(request.user, student):
        raise PermissionDenied("Нет доступа к карточке ученика.")
    try:
        _, raw_token = create_account_invite(student=student, created_by=request.user)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        path = reverse("students:accept-invite", kwargs={"token": raw_token})
        request.session["student_invite_url"] = request.build_absolute_uri(path)
        messages.success(request, "Ссылка создана и действует 7 дней.")
    return redirect("students:edit", public_id=student.public_id)


@login_required
def account_invite_accept(request, token):
    try:
        student = accept_account_invite(raw_token=token, user=request.user)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        messages.success(request, f"Аккаунт привязан к карточке «{student.full_name}».")
    return redirect("accounts:dashboard-settings")
