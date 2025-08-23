"""URL patterns for the groups app."""

from django.urls import path

from . import views

app_name = "groups"

urlpatterns = [
    path("join/", views.join_group, name="join_group"),
    path("<int:pk>/", views.group_detail, name="group_detail"),
    path("<int:pk>/generate-code/", views.generate_code, name="generate_code"),
]
