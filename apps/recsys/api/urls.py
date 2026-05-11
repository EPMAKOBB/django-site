from django.urls import path


from .views import (
    AttemptCreateView,
    CurrentVariantAssignmentListView,
    NextTaskView,
    PastVariantAssignmentListView,
    ProgressView,
    RecommendationHistoryView,
    RecommendationListView,
    SkillListView,
    SkillGroupListView,
    TaskTypeListView,
    TrainingCurrentSessionView,
    TrainingTypeFilterView,
    TrainingSessionDetailView,
    TrainingSessionEndView,
    TrainingSessionNextView,
    TrainingSessionStartView,
    TrainingSessionSubmitView,
    VariantAssignmentHistoryView,
    VariantAttemptFinalizeView,
    VariantAttemptHeartbeatView,
    VariantAttemptStartView,
    VariantAttemptDetailView,
    VariantTaskFocusView,
    VariantTaskSaveView,
    VariantTaskClearView,
    VariantTaskSubmitView,
)


urlpatterns = [
    path("api/skills/", SkillListView.as_view(), name="skill-list"),
    path("api/task-types/", TaskTypeListView.as_view(), name="task-type-list"),
    path("api/attempts/", AttemptCreateView.as_view(), name="attempt-create"),
    path("api/next-task/", NextTaskView.as_view(), name="next-task"),
    path("api/recommendations/", RecommendationListView.as_view(), name="recommendation-list"),
    path("api/recommendation-history/", RecommendationHistoryView.as_view(), name="recommendation-history"),
    path("api/progress/", ProgressView.as_view(), name="progress"),
    path("api/training/type-filters/", TrainingTypeFilterView.as_view(), name="training-type-filters"),
    path("api/training/sessions/current/", TrainingCurrentSessionView.as_view(), name="training-session-current"),
    path("api/training/sessions/", TrainingSessionStartView.as_view(), name="training-session-start"),
    path("api/training/sessions/<int:session_id>/", TrainingSessionDetailView.as_view(), name="training-session-detail"),
    path("api/training/sessions/<int:session_id>/submit/", TrainingSessionSubmitView.as_view(), name="training-session-submit"),
    path("api/training/sessions/<int:session_id>/next/", TrainingSessionNextView.as_view(), name="training-session-next"),
    path("api/training/sessions/<int:session_id>/end/", TrainingSessionEndView.as_view(), name="training-session-end"),
    path(
        "api/exam-versions/<int:exam_version_id>/skill-groups/",
        SkillGroupListView.as_view(),
        name="skill-group-list",
    ),
    # Variant workflow endpoints – all require authenticated students.
    path(
        "api/variants/assignments/current/",
        CurrentVariantAssignmentListView.as_view(),
        name="variant-assignments-current",
    ),
    path(
        "api/variants/assignments/past/",
        PastVariantAssignmentListView.as_view(),
        name="variant-assignments-past",
    ),
    path(
        "api/variants/assignments/<int:assignment_id>/attempts/start/",
        VariantAttemptStartView.as_view(),
        name="variant-attempt-start",
    ),
    path(
        "api/variants/attempts/<int:attempt_id>/",
        VariantAttemptDetailView.as_view(),
        name="variant-attempt-detail",
    ),
    path(
        "api/variants/attempts/<int:attempt_id>/heartbeat/",
        VariantAttemptHeartbeatView.as_view(),
        name="variant-attempt-heartbeat",
    ),
    path(
        "api/variants/attempts/<int:attempt_id>/tasks/<int:variant_task_id>/submit/",
        VariantTaskSubmitView.as_view(),
        name="variant-task-submit",
    ),
    path(
        "api/variants/attempts/<int:attempt_id>/tasks/<int:variant_task_id>/save/",
        VariantTaskSaveView.as_view(),
        name="variant-task-save",
    ),
    path(
        "api/variants/attempts/<int:attempt_id>/tasks/<int:variant_task_id>/clear/",
        VariantTaskClearView.as_view(),
        name="variant-task-clear",
    ),
    path(
        "api/variants/attempts/<int:attempt_id>/tasks/<int:variant_task_id>/focus/",
        VariantTaskFocusView.as_view(),
        name="variant-task-focus",
    ),
    path(
        "api/variants/attempts/<int:attempt_id>/finalize/",
        VariantAttemptFinalizeView.as_view(),
        name="variant-attempt-finalize",
    ),
    path(
        "api/variants/assignments/<int:assignment_id>/history/",
        VariantAssignmentHistoryView.as_view(),
        name="variant-assignment-history",
    ),
]


