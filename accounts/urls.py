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
    path("dashboard/students/", views.dashboard_students, name="dashboard-students"),
    path("dashboard/classes/", views.dashboard_classes, name="dashboard-classes"),
    path("dashboard/assignments/create/", views.assignment_create, name="assignment-create"),
    path(
        "dashboard/attempts/<int:attempt_id>/",
        views.variant_attempt_work,
        name="variant-attempt-work",
    ),
    # Variant basket routes (teacher only)
    path("dashboard/variant-basket/", views.variant_basket_edit, name="variant-basket-edit"),
    path("dashboard/variant-basket/add/", views.variant_basket_add, name="variant-basket-add"),
    path("dashboard/variant-basket/remove/", views.variant_basket_remove, name="variant-basket-remove"),
    path("dashboard/variant-basket/reset/", views.variant_basket_reset, name="variant-basket-reset"),
    path("dashboard/settings/", views.dashboard_settings, name="dashboard-settings"),
    path("dashboard/methodist/", views.dashboard_methodist, name="dashboard-methodist"),
    path("join/teacher/<str:code>/", views.join_teacher_with_code, name="join-teacher"),
    path("join/class/<str:code>/", views.join_class_with_code, name="join-class"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html", authentication_form=LoginForm
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
