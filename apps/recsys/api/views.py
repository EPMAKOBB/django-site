from rest_framework import generics, permissions
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
from .serializers import (
    AttemptSerializer,
    SkillGroupSerializer,
    SkillMasterySerializer,
    SkillSerializer,
    TaskSerializer,
    TaskTypeSerializer,
    TypeMasterySerializer,
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
        return Response(TaskSerializer(task).data)


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
        type_masteries = TypeMasterySerializer(
            TypeMastery.objects.filter(user=user), many=True
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

