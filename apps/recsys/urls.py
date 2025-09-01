from django.urls import path
from .views import attempts_view, next_task_view, progress_view

urlpatterns = [
    path('attempts/', attempts_view, name='api-attempts'),
    path('next-task/', next_task_view, name='api-next-task'),
    path('progress/', progress_view, name='api-progress'),
]
