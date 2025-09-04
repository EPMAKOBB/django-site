from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect


from .forms import SignupForm, UserUpdateForm, PasswordChangeForm


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
    context = {"active_tab": "subjects", "role": role}
    return render(request, "accounts/dashboard/subjects.html", context)


@login_required
def dashboard_courses(request):
    """Display a placeholder courses dashboard."""
    role = _get_dashboard_role(request)
    context = {"active_tab": "courses", "role": role}
    return render(request, "accounts/dashboard/courses.html", context)

