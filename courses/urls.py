from django.urls import path

from .views import module_detail

app_name = "courses"

urlpatterns = [
    path(
        "courses/<slug:course_slug>/modules/<slug:module_slug>/",
        module_detail,
        name="module-detail",
    ),
]
