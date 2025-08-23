"""Views for managing groups and invitation codes."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import InvitationCodeForm
from .models import Group, InvitationCode


@login_required
def join_group(request):
    """Allow a student to join a group using an invitation code."""

    form = InvitationCodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        code = form.cleaned_data["code"].upper()
        try:
            invitation = InvitationCode.objects.get(code=code, used_by__isnull=True)
        except InvitationCode.DoesNotExist:
            messages.error(request, "Invalid invitation code.")
        else:
            group = invitation.group
            group.students.add(request.user)
            invitation.used_by = request.user
            invitation.save()
            messages.success(request, f"You have joined {group.name}.")
            return redirect("groups:join_group")
    groups = request.user.student_groups.all()
    return render(request, "groups/join_group.html", {"form": form, "groups": groups})


@login_required
def group_detail(request, pk):
    """Display group details for the teacher."""

    group = get_object_or_404(Group, pk=pk, teacher=request.user)
    codes = group.codes.filter(used_by__isnull=True)
    students = group.students.all()
    return render(
        request,
        "groups/group_detail.html",
        {"group": group, "codes": codes, "students": students},
    )


@login_required
def generate_code(request, pk):
    """Generate a new invitation code for the given group."""

    group = get_object_or_404(Group, pk=pk, teacher=request.user)
    if request.method == "POST":
        InvitationCode.objects.create(group=group)
        messages.success(request, "Invitation code generated.")
    return redirect("groups:group_detail", pk=group.pk)
