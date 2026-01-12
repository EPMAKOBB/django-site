from rest_framework import generics, permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import (
    Attempt,
    RecommendationLog,
    Skill,
    SkillMastery,
    SkillGroup,
    Task,
    TaskType,
    TypeMastery,
)
from ..service_utils import variants as variant_service
from ..service_utils.type_progress import build_type_progress_map
from .serializers import (
    AttemptSerializer,
    SkillGroupSerializer,
    SkillMasterySerializer,
    SkillSerializer,
    TaskSerializer,
    TaskTypeSerializer,
    TypeMasterySerializer,
    VariantAssignmentHistorySerializer,
    VariantAssignmentSerializer,
    VariantAttemptSerializer,
)


class SkillListView(generics.ListAPIView):
    queryset = Skill.objects.all()
    serializer_class = SkillSerializer
    permission_classes = [permissions.IsAuthenticated]


class TaskTypeListView(generics.ListAPIView):
    queryset = TaskType.objects.all()
    serializer_class = TaskTypeSerializer
    permission_classes = [permissions.IsAuthenticated]


class AttemptCreateView(generics.CreateAPIView):
    queryset = Attempt.objects.all()
    serializer_class = AttemptSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class NextTaskView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        task = (
            Task.objects.exclude(attempts__user=request.user)
            .order_by("id")
            .first()
        )
        if not task:
            return Response({"detail": "No tasks available"}, status=404)
        RecommendationLog.objects.create(user=request.user, task=task)
        serializer = TaskSerializer(task, context={"request": request})
        return Response(serializer.data)


class ProgressView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        attempts = Attempt.objects.filter(user=user)
        total_attempts = attempts.count()
        correct_attempts = attempts.filter(is_correct=True).count()

        skill_masteries = SkillMasterySerializer(
            SkillMastery.objects.filter(user=user), many=True
        ).data
        type_masteries_qs = TypeMastery.objects.filter(user=user).select_related("task_type")
        type_ids = list(type_masteries_qs.values_list("task_type_id", flat=True))
        type_progress_map = (
            build_type_progress_map(user=user, task_type_ids=type_ids) if type_ids else {}
        )
        type_masteries = TypeMasterySerializer(
            type_masteries_qs,
            many=True,
            context={
                "request": request,
                "type_progress_map": type_progress_map,
            },
        ).data

        data = {
            "attempts": {
                "total": total_attempts,
                "correct": correct_attempts,
            },
            "skill_masteries": skill_masteries,
            "type_masteries": type_masteries,
        }
        return Response(data)


class SkillGroupListView(generics.ListAPIView):
    serializer_class = SkillGroupSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        exam_version_id = self.kwargs["exam_version_id"]
        return SkillGroup.objects.filter(
            exam_version_id=exam_version_id
        ).prefetch_related("items__skill").order_by("id")


class VariantAssignmentListMixin(APIView):
    """Base view for returning variant assignments for the current user."""

    permission_classes = [permissions.IsAuthenticated]

    def _get_assignments(self, request):
        assignments = variant_service.get_assignments_for_user(request.user)
        current, past = variant_service.split_assignments(assignments)
        return current, past


class CurrentVariantAssignmentListView(VariantAssignmentListMixin):
    """List assignments that can still be taken or have an active attempt."""

    def get(self, request, *args, **kwargs):
        current, _ = self._get_assignments(request)
        serializer = VariantAssignmentSerializer(
            current, many=True, context={"request": request}
        )
        return Response(serializer.data)


class PastVariantAssignmentListView(VariantAssignmentListMixin):
    """List assignments where no further attempts are possible."""

    def get(self, request, *args, **kwargs):
        _, past = self._get_assignments(request)
        serializer = VariantAssignmentSerializer(
            past, many=True, context={"request": request}
        )
        return Response(serializer.data)


class VariantAttemptStartView(APIView):
    """Start a new attempt for the selected assignment."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, assignment_id: int, *args, **kwargs):
        attempt = variant_service.start_new_attempt(request.user, assignment_id)
        attempt = variant_service.get_attempt_with_prefetch(request.user, attempt.id)
        serializer = VariantAttemptSerializer(attempt, context={"request": request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class VariantAttemptDetailView(APIView):
    """Return attempt with tasks progress."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, attempt_id: int, *args, **kwargs):
        attempt = variant_service.get_attempt_with_prefetch(request.user, attempt_id)
        serializer = VariantAttemptSerializer(attempt, context={"request": request})
        return Response(serializer.data)


class VariantAttemptHeartbeatView(APIView):
    """Lightweight heartbeat for keeping timed attempts in sync."""

    permission_classes = [permissions.IsAuthenticated]

    class InputSerializer(serializers.Serializer):
        client_id = serializers.UUIDField(required=False, allow_null=True)

    def post(self, request, attempt_id: int, *args, **kwargs):
        serializer = self.InputSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        attempt = variant_service.heartbeat_attempt(
            request.user,
            attempt_id,
            client_id=serializer.validated_data.get("client_id"),
        )
        time_left = variant_service.get_time_left(attempt)
        payload = {
            "completed": attempt.completed_at is not None,
            "time_left_seconds": int(time_left.total_seconds()) if time_left else None,
        }
        return Response(payload)


class VariantTaskFocusView(APIView):
    """Mark a task as opened to start/stop per-task timers."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, attempt_id: int, variant_task_id: int, *args, **kwargs):
        attempt = variant_service.set_active_task(request.user, attempt_id, variant_task_id)
        attempt = variant_service.get_attempt_with_prefetch(request.user, attempt.id)
        serializer = VariantAttemptSerializer(attempt, context={"request": request})
        return Response(serializer.data)


class VariantTaskSaveView(APIView):
    """Save draft answer for a task (without scoring)."""

    permission_classes = [permissions.IsAuthenticated]

    class InputSerializer(serializers.Serializer):
        answer = serializers.JSONField()

    def post(self, request, attempt_id: int, variant_task_id: int, *args, **kwargs):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        generation_attempt = variant_service.save_task_response(
            request.user,
            attempt_id,
            variant_task_id,
            answer=serializer.validated_data["answer"],
        )
        attempt = variant_service.get_attempt_with_prefetch(request.user, generation_attempt.variant_attempt_id)
        response_serializer = VariantAttemptSerializer(attempt, context={"request": request})
        return Response(response_serializer.data)


class VariantTaskClearView(APIView):
    """Clear saved draft answer and restart timer."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, attempt_id: int, variant_task_id: int, *args, **kwargs):
        generation_attempt = variant_service.clear_task_response(
            request.user,
            attempt_id,
            variant_task_id,
        )
        attempt = variant_service.get_attempt_with_prefetch(request.user, generation_attempt.variant_attempt_id)
        serializer = VariantAttemptSerializer(attempt, context={"request": request})
        return Response(serializer.data)


class VariantTaskSubmitView(APIView):
    """Persist an answer for a single task inside the attempt."""

    permission_classes = [permissions.IsAuthenticated]

    class InputSerializer(serializers.Serializer):
        is_correct = serializers.BooleanField()
        task_snapshot = serializers.JSONField(required=False)

    def post(self, request, attempt_id: int, variant_task_id: int, *args, **kwargs):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = variant_service.submit_task_answer(
            request.user,
            attempt_id,
            variant_task_id,
            **serializer.validated_data,
        )
        attempt = variant_service.get_attempt_with_prefetch(request.user, result.attempt.id)
        response_serializer = VariantAttemptSerializer(
            attempt, context={"request": request}
        )
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class VariantAttemptFinalizeView(APIView):
    """Mark an attempt as finished."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, attempt_id: int, *args, **kwargs):
        attempt = variant_service.finalize_attempt(request.user, attempt_id)
        attempt = variant_service.get_attempt_with_prefetch(request.user, attempt.id)
        serializer = VariantAttemptSerializer(attempt, context={"request": request})
        return Response(serializer.data)


class VariantAssignmentHistoryView(APIView):
    """Return full history of attempts for an assignment."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, assignment_id: int, *args, **kwargs):
        assignment = variant_service.get_assignment_history(request.user, assignment_id)
        serializer = VariantAssignmentHistorySerializer(
            assignment, context={"request": request}
        )
        return Response(serializer.data)

