from rest_framework import serializers

from ..models import (
    Attempt,
    RecommendationLog,
    Skill,
    SkillMastery,
    Subject,
    Task,
    TaskSkill,
    TaskType,
    TypeMastery,
)


class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ["id", "name", "slug"]


class SkillSerializer(serializers.ModelSerializer):
    subject = SubjectSerializer(read_only=True)

    class Meta:
        model = Skill
        fields = ["id", "name", "description", "subject"]


class TaskTypeSerializer(serializers.ModelSerializer):
    subject = SubjectSerializer(read_only=True)

    class Meta:
        model = TaskType
        fields = ["id", "name", "description", "subject"]


class TaskSkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskSkill
        fields = ["id", "task", "skill", "weight"]


class TaskSerializer(serializers.ModelSerializer):
    type = TaskTypeSerializer(read_only=True)
    skills = SkillSerializer(many=True, read_only=True)
    subject = SubjectSerializer(source="type.subject", read_only=True)

    class Meta:
        model = Task
        fields = ["id", "subject", "type", "title", "description", "skills"]


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
    "RecommendationLogSerializer",
    "SkillSerializer",
    "SkillMasterySerializer",
    "SubjectSerializer",
    "TaskSerializer",
    "TaskSkillSerializer",
    "TaskTypeSerializer",
    "TypeMasterySerializer",
]

