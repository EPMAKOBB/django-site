from collections.abc import Mapping
from copy import deepcopy

from rest_framework import serializers

from django.utils import timezone

from ..models import (
    Attempt,
    RecommendationLog,
    Skill,
    SkillMastery,
    Task,
    TaskSkill,
    TaskTag,
    TaskType,
    SkillGroup,
    SkillGroupItem,
    TypeMastery,
    VariantAssignment,
    VariantAttempt,
    VariantTask,
    VariantTaskAttempt,
    VariantTemplate,
    resolve_media_url,
)
from ..service_utils import variants as variant_service


def _clamp_mastery_value(value):
    """Ensure mastery percentages stay within [0.0, 1.0]."""
    value = float(value or 0.0)
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


class SkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = ["id", "subject", "name", "description"]


class TaskTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskTag
        fields = ["id", "subject", "name", "slug"]
        read_only_fields = fields


class TaskTypeSerializer(serializers.ModelSerializer):
    exam_version = serializers.PrimaryKeyRelatedField(read_only=True)
    required_tags = TaskTagSerializer(many=True, read_only=True)

    class Meta:
        model = TaskType
        fields = [
            "id",
            "subject",
            "exam_version",
            "name",
            "slug",
            "description",
            "display_order",
            "required_tags",
        ]


class TaskSkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskSkill
        fields = ["id", "task", "skill", "weight"]


class TaskSerializer(serializers.ModelSerializer):
    type = TaskTypeSerializer(read_only=True)
    skills = SkillSerializer(many=True, read_only=True)
    tags = TaskTagSerializer(many=True, read_only=True)
    subject = serializers.PrimaryKeyRelatedField(read_only=True)
    exam_version = serializers.PrimaryKeyRelatedField(read_only=True)
    image = serializers.SerializerMethodField()

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
            "tags",
            "is_dynamic",
            "dynamic_mode",
            "generator_slug",
            "default_payload",
            "rendering_strategy",
            "image",
            "difficulty_level",
            "correct_answer",
        ]

    def get_image(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request") if isinstance(self.context, dict) else None
        url = resolve_media_url(obj.image.url)
        if request is not None:
            return request.build_absolute_uri(url)
        return url


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
    mastery = serializers.SerializerMethodField()

    class Meta:
        model = SkillMastery
        fields = ["id", "skill", "mastery"]

    def get_mastery(self, obj: SkillMastery) -> float:
        return _clamp_mastery_value(obj.mastery)


class TypeMasterySerializer(serializers.ModelSerializer):
    task_type = TaskTypeSerializer(read_only=True)
    mastery = serializers.SerializerMethodField()
    effective_mastery = serializers.SerializerMethodField()
    coverage_ratio = serializers.SerializerMethodField()
    required_count = serializers.SerializerMethodField()
    covered_count = serializers.SerializerMethodField()
    required_tags = serializers.SerializerMethodField()
    covered_tag_ids = serializers.SerializerMethodField()
    tag_progress = serializers.SerializerMethodField()

    class Meta:
        model = TypeMastery
        fields = [
            "id",
            "task_type",
            "mastery",
            "effective_mastery",
            "coverage_ratio",
            "required_count",
            "covered_count",
            "required_tags",
            "covered_tag_ids",
            "tag_progress",
        ]

    def _get_progress_info(self, obj: TypeMastery):
        progress_map = self.context.get("type_progress_map") or {}
        return progress_map.get(obj.task_type_id)

    def get_mastery(self, obj: TypeMastery) -> float:
        return _clamp_mastery_value(obj.mastery)

    def get_effective_mastery(self, obj: TypeMastery) -> float:
        info = self._get_progress_info(obj)
        mastery = _clamp_mastery_value(obj.mastery)
        if info is None:
            return mastery
        return info.effective_mastery

    def get_coverage_ratio(self, obj: TypeMastery) -> float:
        info = self._get_progress_info(obj)
        return info.coverage_ratio if info is not None else 1.0

    def get_required_count(self, obj: TypeMastery) -> int:
        info = self._get_progress_info(obj)
        return info.required_count if info is not None else 0

    def get_covered_count(self, obj: TypeMastery) -> int:
        info = self._get_progress_info(obj)
        return info.covered_count if info is not None else 0

    def get_required_tags(self, obj: TypeMastery):
        info = self._get_progress_info(obj)
        if info is None:
            return []
        serializer = TaskTagSerializer(info.required_tags, many=True, context=self.context)
        return serializer.data

    def get_covered_tag_ids(self, obj: TypeMastery):
        info = self._get_progress_info(obj)
        if info is None:
            return []
        return list(info.covered_tag_ids)

    def get_tag_progress(self, obj: TypeMastery):
        info = self._get_progress_info(obj)
        if info is None:
            return []
        return [
            {
                "tag_id": entry.tag.id,
                "tag_name": entry.tag.name,
                "solved_count": entry.solved_count,
                "total_count": entry.total_count,
                "ratio": entry.ratio,
            }
            for entry in info.tag_progress
        ]


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
            "score",
            "max_score",
            "time_spent",
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
    primary_summary = serializers.SerializerMethodField()
    secondary_summary = serializers.SerializerMethodField()

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
            "primary_summary",
            "secondary_summary",
        ]
        read_only_fields = fields

    def _get_primary_summary(self, obj: VariantAttempt) -> dict:
        cached = getattr(obj, "_primary_summary_cache", None)
        if cached is None:
            cached = variant_service.calculate_attempt_primary_summary(obj)
            obj._primary_summary_cache = cached
        return cached

    def get_time_left(self, obj: VariantAttempt):
        remaining = variant_service.get_time_left(obj)
        if remaining is None:
            return None
        return remaining

    def get_is_completed(self, obj: VariantAttempt) -> bool:
        return obj.completed_at is not None

    def get_tasks_progress(self, obj: VariantAttempt):
        progress = []
        is_completed = obj.completed_at is not None
        for item in variant_service.build_tasks_progress(obj):
            attempts_serializer = VariantTaskAttemptSerializer(
                item["attempts"], many=True, context=self.context
            )
            saved_response_updated_at = item.get("saved_response_updated_at")
            if saved_response_updated_at is not None:
                saved_response_updated_at = timezone.localtime(saved_response_updated_at).isoformat()
            attempts_data = attempts_serializer.data
            task_snapshot = item.get("task_snapshot")
            if not is_completed:
                for attempt_data in attempts_data:
                    task_payload = attempt_data.get("task")
                    if isinstance(task_payload, dict):
                        task_payload.pop("correct_answer", None)
                    attempt_snapshot = attempt_data.get("task_snapshot")
                    if isinstance(attempt_snapshot, dict):
                        attempt_snapshot.pop("correct_answer", None)
                        nested_task = attempt_snapshot.get("task")
                        if isinstance(nested_task, dict):
                            nested_task.pop("correct_answer", None)
                if isinstance(task_snapshot, Mapping):
                    sanitized_snapshot = deepcopy(task_snapshot)
                    sanitized_snapshot.pop("correct_answer", None)
                    nested_task = sanitized_snapshot.get("task")
                    if isinstance(nested_task, Mapping):
                        nested_task = dict(nested_task)
                        nested_task.pop("correct_answer", None)
                        sanitized_snapshot["task"] = nested_task
                    task_snapshot = sanitized_snapshot
            progress.append(
                {
                    "variant_task_id": item["variant_task_id"],
                    "task_id": item["task_id"],
                    "order": item["order"],
                    "task_type_name": item.get("task_type_name"),
                    "answer_schema": item.get("answer_schema"),
                    "task_rendering_strategy": item.get("task_rendering_strategy"),
                    "task_body_html": item.get("task_body_html"),
                    "max_score": item.get("max_score"),
                    "max_attempts": item["max_attempts"],
                    "attempts_used": item["attempts_used"],
                    "is_completed": item["is_completed"],
                    "task_snapshot": task_snapshot,
                    "saved_response": item.get("saved_response"),
                    "saved_response_updated_at": saved_response_updated_at,
                    "attempts": attempts_data,
                    "time_spent": item.get("time_spent"),
                }
            )
        return progress

    def get_primary_summary(self, obj: VariantAttempt):
        return self._get_primary_summary(obj)

    def get_secondary_summary(self, obj: VariantAttempt):
        exam_version = getattr(obj.assignment.template, "exam_version", None)
        scale = variant_service.get_active_score_scale(exam_version)
        if not scale:
            return None
        summary = self._get_primary_summary(obj)
        primary_total = summary.get("primary_total", 0)
        secondary_score, over_limit = scale.to_secondary(primary_total)
        max_secondary = max(scale.mapping) if scale.mapping else None
        return {
            "score": secondary_score,
            "over_limit": over_limit,
            "max": max_secondary,
        }


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


