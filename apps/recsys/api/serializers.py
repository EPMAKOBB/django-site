from rest_framework import serializers

from ..models import (
    Attempt,
    RecommendationLog,
    Skill,
    SkillMastery,
    Task,
    TaskSkill,
    TaskType,
    SkillGroup,
    SkillGroupItem,
    TypeMastery,
    VariantAssignment,
    VariantAttempt,
    VariantTask,
    VariantTaskAttempt,
    VariantTemplate,
)
from ..service_utils import variants as variant_service


class SkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = ["id", "subject", "name", "description"]


class TaskTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskType
        fields = ["id", "subject", "name", "description"]


class TaskSkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskSkill
        fields = ["id", "task", "skill", "weight"]


class TaskSerializer(serializers.ModelSerializer):
    type = TaskTypeSerializer(read_only=True)
    skills = SkillSerializer(many=True, read_only=True)
    subject = serializers.PrimaryKeyRelatedField(read_only=True)
    exam_version = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Task
        fields = [
            "id",
            "subject",
            "exam_version",
            "type",
            "title",
            "description",
            "skills",
        ]


class AttemptSerializer(serializers.ModelSerializer):
    variant_task_attempt = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Attempt
        fields = [
            "id",
            "task",
            "is_correct",
            "attempts_count",
            "weight",
            "variant_task_attempt",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "attempts_count",
            "weight",
            "variant_task_attempt",
            "created_at",
            "updated_at",
        ]


class SkillMasterySerializer(serializers.ModelSerializer):
    skill = SkillSerializer(read_only=True)

    class Meta:
        model = SkillMastery
        fields = ["id", "skill", "mastery"]


class TypeMasterySerializer(serializers.ModelSerializer):
    task_type = TaskTypeSerializer(read_only=True)

    class Meta:
        model = TypeMastery
        fields = ["id", "task_type", "mastery"]


class RecommendationLogSerializer(serializers.ModelSerializer):
    task = TaskSerializer(read_only=True)

    class Meta:
        model = RecommendationLog
        fields = [
            "id",
            "task",
            "completed",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class SkillGroupItemSerializer(serializers.ModelSerializer):
    skill = SkillSerializer(read_only=True)

    class Meta:
        model = SkillGroupItem
        fields = ["id", "skill", "label", "order"]


class SkillGroupSerializer(serializers.ModelSerializer):
    items = SkillGroupItemSerializer(many=True, read_only=True)
    exam_version = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = SkillGroup
        fields = ["id", "exam_version", "title", "items"]


__all__ = [
    "AttemptSerializer",
    "RecommendationLogSerializer",
    "SkillSerializer",
    "SkillMasterySerializer",
    "TaskSerializer",
    "TaskSkillSerializer",
    "TaskTypeSerializer",
    "TypeMasterySerializer",
    "SkillGroupItemSerializer",
    "SkillGroupSerializer",
    "VariantTaskSerializer",
    "VariantTemplateSerializer",
    "VariantTaskAttemptSerializer",
    "VariantAttemptSerializer",
    "VariantAssignmentSerializer",
    "VariantAssignmentHistorySerializer",
]


class VariantTaskSerializer(serializers.ModelSerializer):
    task = TaskSerializer(read_only=True)

    class Meta:
        model = VariantTask
        fields = ["id", "task", "order", "max_attempts"]


class VariantTemplateSerializer(serializers.ModelSerializer):
    tasks = VariantTaskSerializer(source="template_tasks", many=True, read_only=True)

    class Meta:
        model = VariantTemplate
        fields = ["id", "name", "description", "time_limit", "max_attempts", "tasks"]


class VariantTaskAttemptSerializer(serializers.ModelSerializer):
    task = TaskSerializer(read_only=True)

    class Meta:
        model = VariantTaskAttempt
        fields = [
            "id",
            "variant_task",
            "task",
            "attempt_number",
            "is_correct",
            "task_snapshot",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class VariantAttemptSerializer(serializers.ModelSerializer):
    time_limit = serializers.DurationField(
        source="assignment.template.time_limit", read_only=True
    )
    time_left = serializers.SerializerMethodField()
    is_completed = serializers.SerializerMethodField()
    tasks_progress = serializers.SerializerMethodField()

    class Meta:
        model = VariantAttempt
        fields = [
            "id",
            "assignment",
            "attempt_number",
            "started_at",
            "completed_at",
            "time_spent",
            "time_limit",
            "time_left",
            "is_completed",
            "tasks_progress",
        ]
        read_only_fields = fields

    def get_time_left(self, obj: VariantAttempt):
        remaining = variant_service.get_time_left(obj)
        if remaining is None:
            return None
        return remaining

    def get_is_completed(self, obj: VariantAttempt) -> bool:
        return obj.completed_at is not None

    def get_tasks_progress(self, obj: VariantAttempt):
        progress = []
        for item in variant_service.build_tasks_progress(obj):
            attempts_serializer = VariantTaskAttemptSerializer(
                item["attempts"], many=True, context=self.context
            )
            progress.append(
                {
                    "variant_task_id": item["variant_task_id"],
                    "task_id": item["task_id"],
                    "order": item["order"],
                    "max_attempts": item["max_attempts"],
                    "attempts_used": item["attempts_used"],
                    "is_completed": item["is_completed"],
                    "attempts": attempts_serializer.data,
                }
            )
        return progress


class VariantAssignmentSerializer(serializers.ModelSerializer):
    template = VariantTemplateSerializer(read_only=True)
    active_attempt = serializers.SerializerMethodField()
    attempts_left = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()

    class Meta:
        model = VariantAssignment
        fields = [
            "id",
            "template",
            "deadline",
            "started_at",
            "created_at",
            "active_attempt",
            "attempts_left",
            "progress",
        ]
        read_only_fields = fields

    def get_active_attempt(self, obj: VariantAssignment):
        active = next((a for a in obj.attempts.all() if a.completed_at is None), None)
        if not active:
            return None
        serializer = VariantAttemptSerializer(active, context=self.context)
        return serializer.data

    def get_attempts_left(self, obj: VariantAssignment):
        return variant_service.get_attempts_left(obj)

    def get_progress(self, obj: VariantAssignment):
        return variant_service.calculate_assignment_progress(obj)


class VariantAssignmentHistorySerializer(VariantAssignmentSerializer):
    attempts = VariantAttemptSerializer(many=True, read_only=True)

    class Meta(VariantAssignmentSerializer.Meta):
        fields = VariantAssignmentSerializer.Meta.fields + ["attempts"]


