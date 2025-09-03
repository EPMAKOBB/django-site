from rest_framework import serializers

from ..models import (
    Attempt,
    ExamVersion,
    RecommendationLog,
    Skill,
    SkillMastery,
    Task,
    TaskSkill,
    TaskType,
    TypeMastery,
)


class ExamVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExamVersion
        fields = ["id", "subject", "exam_type", "year", "label"]


class SkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = ["id", "exam_version", "name", "description"]


class TaskTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskType
        fields = ["id", "exam_version", "name", "description"]


class TaskSkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskSkill
        fields = ["id", "task", "skill", "weight"]


class TaskSerializer(serializers.ModelSerializer):
    type = TaskTypeSerializer(read_only=True)
    skills = SkillSerializer(many=True, read_only=True)

    class Meta:
        model = Task
        fields = ["id", "type", "title", "description", "skills"]


class AttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attempt
        fields = ["id", "task", "is_correct", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


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


__all__ = [
    "AttemptSerializer",
    "ExamVersionSerializer",
    "RecommendationLogSerializer",
    "SkillSerializer",
    "SkillMasterySerializer",
    "TaskSerializer",
    "TaskSkillSerializer",
    "TaskTypeSerializer",
    "TypeMasterySerializer",
]

