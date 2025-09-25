from django.urls import path
from django.contrib.auth import views as auth_views

from .forms import LoginForm
from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("dashboard/", views.progress, name="dashboard"),
    path(
        "dashboard/assignments/<int:assignment_id>/",
        views.assignment_detail,
        name="assignment-detail",
    ),
    path(
        "dashboard/assignments/<int:assignment_id>/results/",
        views.assignment_result,
        name="assignment-result",
    ),
    path("dashboard/subjects/", views.dashboard_subjects, name="dashboard-subjects"),
    path("dashboard/courses/", views.dashboard_courses, name="dashboard-courses"),
    path("dashboard/teachers/", views.dashboard_teachers, name="dashboard-teachers"),
    path("dashboard/classes/", views.dashboard_classes, name="dashboard-classes"),
    path("dashboard/settings/", views.dashboard_settings, name="dashboard-settings"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html", authentication_form=LoginForm
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
