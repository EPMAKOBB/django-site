"""URL configuration for the students app."""

from django.urls import path

from .views import dashboard

app_name = "students"

urlpatterns = [
    path("", dashboard, name="dashboard"),
]

