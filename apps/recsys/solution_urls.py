from django.urls import path
from . import solution_views as views

urlpatterns = [
    path('works/<int:attempt_id>/', views.solution_list, name='written-solution-list'),
    path('works/<int:attempt_id>/tasks/<int:task_id>/', views.workspace, name='written-solution'),
    path('photos/<int:photo_id>/', views.photo, name='solution-photo'),
    path('<int:solution_id>/qr/', views.qr, name='solution-qr'),
    path('<int:solution_id>/status/', views.status, name='solution-status'),
    path('phone/<str:token>/', views.phone, name='solution-phone'),
    path('phone/<str:token>/photos/<int:photo_id>/', views.phone_photo, name='solution-phone-photo'),
]
