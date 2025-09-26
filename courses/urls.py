from django.urls import path

from . import views

app_name = "courses"

urlpatterns = [
    path("<slug:course_slug>/<slug:module_slug>/", views.module_detail, name="module-detail"),
]
