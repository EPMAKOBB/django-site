from django.urls import path

from . import views


app_name = "lessons"

urlpatterns = [
    path("", views.schedule, name="schedule"),
    path("events/", views.calendar_events, name="calendar-events"),
    path("create/", views.lesson_create, name="lesson-create"),
    path("series/create/", views.series_create, name="series-create"),
    path("series/<int:series_id>/edit/", views.series_edit, name="series-edit"),
    path("series/<int:series_id>/action/", views.series_action, name="series-action"),
    path("timezone/", views.timezone_settings, name="timezone-settings"),
    path(
        "<int:lesson_id>/calendar-reschedule/",
        views.calendar_reschedule,
        name="calendar-reschedule",
    ),
    path("<int:lesson_id>/reschedule/", views.reschedule_request, name="reschedule"),
    path("<int:lesson_id>/action/", views.lesson_action, name="lesson-action"),
    path(
        "reschedule/<int:request_id>/resolve/",
        views.reschedule_resolve,
        name="reschedule-resolve",
    ),
]
