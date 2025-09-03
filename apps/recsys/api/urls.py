from django.urls import path


from .views import (
    AttemptCreateView,
    NextTaskView,
    ProgressView,
    SkillListView,
    SkillGroupListView,
    TaskTypeListView,
)


urlpatterns = [
    path("api/skills/", SkillListView.as_view(), name="skill-list"),
    path("api/task-types/", TaskTypeListView.as_view(), name="task-type-list"),
    path("api/attempts/", AttemptCreateView.as_view(), name="attempt-create"),
    path("api/next-task/", NextTaskView.as_view(), name="next-task"),
    path("api/progress/", ProgressView.as_view(), name="progress"),
    path(
        "api/skill-groups/<int:exam_version_id>/",
        SkillGroupListView.as_view(),
        name="skill-group-list",
    ),
]


