from django.urls import path
from django.contrib.auth import views as auth_views

from .forms import LoginForm
from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("dashboard/", views.progress, name="dashboard"),
    path("dashboard/teachers/", views.dashboard_teachers, name="dashboard-teachers"),
    path("dashboard/classes/", views.dashboard_classes, name="dashboard-classes"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html", authentication_form=LoginForm
        ),
        name="login",
    ),
]
