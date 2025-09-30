from django.urls import path

from .views import ParserControlView

app_name = "parser_tasks"

urlpatterns = [
    path("control/", ParserControlView.as_view(), name="control"),
]
