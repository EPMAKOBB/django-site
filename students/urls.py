from django.urls import path

from . import views


app_name = "students"

urlpatterns = [
    path("<uuid:public_id>/edit/", views.student_edit, name="edit"),
    path("<uuid:public_id>/invite/", views.account_invite_create, name="create-invite"),
    path("invite/<str:token>/", views.account_invite_accept, name="accept-invite"),
]
