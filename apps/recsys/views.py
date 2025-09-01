
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .models import SkillMastery


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

