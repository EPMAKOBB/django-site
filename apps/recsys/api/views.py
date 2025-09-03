from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import (
    Attempt,
    ExamVersion,
    RecommendationLog,
    Skill,
    SkillMastery,
    Task,
    TaskType,
    TypeMastery,
)
from .serializers import (
    AttemptSerializer,
    ExamVersionSerializer,
    SkillMasterySerializer,
    SkillSerializer,
    TaskSerializer,
    TaskTypeSerializer,
    TypeMasterySerializer,
)


class SkillListView(generics.ListAPIView):
    serializer_class = SkillSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Skill.objects.all()
        exam_version = self.request.query_params.get("exam_version")
        if exam_version:
            qs = qs.filter(exam_version_id=exam_version)
        return qs


class TaskTypeListView(generics.ListAPIView):
    serializer_class = TaskTypeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = TaskType.objects.all()
        exam_version = self.request.query_params.get("exam_version")
        if exam_version:
            qs = qs.filter(exam_version_id=exam_version)
        return qs


class AttemptCreateView(generics.CreateAPIView):
    queryset = Attempt.objects.all()
    serializer_class = AttemptSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class NextTaskView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        exam_version = request.query_params.get("exam_version")
        tasks = Task.objects.all()
        if exam_version:
            tasks = tasks.filter(type__exam_version_id=exam_version)
        task = (
            tasks.exclude(attempts__user=request.user)
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
        exam_version = request.query_params.get("exam_version")
        attempts = Attempt.objects.filter(user=user)
        if exam_version:
            attempts = attempts.filter(task__type__exam_version_id=exam_version)
        total_attempts = attempts.count()
        correct_attempts = attempts.filter(is_correct=True).count()

        skill_masteries_qs = SkillMastery.objects.filter(user=user)
        if exam_version:
            skill_masteries_qs = skill_masteries_qs.filter(
                skill__exam_version_id=exam_version
            )
        skill_masteries = SkillMasterySerializer(
            skill_masteries_qs, many=True
        ).data
        type_masteries_qs = TypeMastery.objects.filter(user=user)
        if exam_version:
            type_masteries_qs = type_masteries_qs.filter(
                task_type__exam_version_id=exam_version
            )
        type_masteries = TypeMasterySerializer(
            type_masteries_qs, many=True
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


class ExamVersionListView(generics.ListAPIView):
    queryset = ExamVersion.objects.select_related("subject").all()
    serializer_class = ExamVersionSerializer
    permission_classes = [permissions.IsAuthenticated]

