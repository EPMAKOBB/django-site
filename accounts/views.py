from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import render, redirect

from apps.recsys.models import SkillMastery

from .forms import SignupForm, UsernameChangeForm


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
    """Display progress for the current user."""
    masteries = (
        SkillMastery.objects.filter(user=request.user)
        .select_related("skill")
        .order_by("skill__name")
    )
    context = {"skill_masteries": masteries, "active_tab": "progress"}
    return render(request, "accounts/dashboard.html", context)


@login_required
def dashboard_teachers(request):
    """Display a placeholder teachers dashboard."""
    context = {"active_tab": "teachers"}
    return render(request, "accounts/dashboard/teachers.html", context)


@login_required
def dashboard_classes(request):
    """Display a placeholder classes dashboard."""
    context = {"active_tab": "classes"}
    return render(request, "accounts/dashboard/classes.html", context)


@login_required
def dashboard_settings(request):
    if request.method == "POST":
        if "username_submit" in request.POST:
            u_form = UsernameChangeForm(request.POST, instance=request.user)
            p_form = PasswordChangeForm(request.user)
            if u_form.is_valid():
                u_form.save()
                return redirect("accounts:dashboard-settings")
        elif "password_submit" in request.POST:
            u_form = UsernameChangeForm(instance=request.user)
            p_form = PasswordChangeForm(request.user, request.POST)
            if p_form.is_valid():
                user = p_form.save()
                update_session_auth_hash(request, user)
                return redirect("accounts:dashboard-settings")
        else:
            u_form = UsernameChangeForm(instance=request.user)
            p_form = PasswordChangeForm(request.user)
    else:
        u_form = UsernameChangeForm(instance=request.user)
        p_form = PasswordChangeForm(request.user)
    context = {"u_form": u_form, "p_form": p_form, "active_tab": "settings"}
    return render(request, "accounts/dashboard/settings.html", context)

