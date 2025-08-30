from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import redirect, render

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
def dashboard(request):
    if request.method == "POST":
        if "username_submit" in request.POST:
            u_form = UsernameChangeForm(request.POST, instance=request.user)
            p_form = PasswordChangeForm(request.user)
            if u_form.is_valid():
                u_form.save()
                return redirect("accounts:dashboard")
        elif "password_submit" in request.POST:
            u_form = UsernameChangeForm(instance=request.user)
            p_form = PasswordChangeForm(request.user, request.POST)
            if p_form.is_valid():
                user = p_form.save()
                update_session_auth_hash(request, user)
                return redirect("accounts:dashboard")
    else:
        u_form = UsernameChangeForm(instance=request.user)
        p_form = PasswordChangeForm(request.user)
    return render(
        request,
        "accounts/dashboard.html",
        {"u_form": u_form, "p_form": p_form},
    )
