from django.urls import path

from .views import ApplicationCreateView

app_name = "applications"

urlpatterns = [
    path("", ApplicationCreateView.as_view(), name="apply"),
]
