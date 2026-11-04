from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.recsys.models import ExamVersion, VariantAttempt
from apps.recsys.service_utils import training_builder as builder, variants
from .serializers import VariantAttemptSerializer
from .training_guards import BoundedTrainingView, TrainingMutationView


class DraftInput(serializers.Serializer):
    action = serializers.ChoiceField(choices=["count", "toggle", "recommend", "clear", "start", "mistakes"])
    revision = serializers.IntegerField(min_value=0)
    lifecycle_revision = serializers.IntegerField(min_value=0, required=False)
    operation_id = serializers.UUIDField(required=False)
    type_id = serializers.IntegerField(min_value=1, required=False)
    task_id = serializers.IntegerField(min_value=1, required=False)
    attempt_id = serializers.IntegerField(min_value=1, required=False)
    count = serializers.IntegerField(min_value=0, max_value=100, required=False)
    selected = serializers.BooleanField(required=False)
    tag_minima = serializers.DictField(child=serializers.IntegerField(min_value=0, max_value=100), required=False)

    def validate_tag_minima(self, value):
        if len(value) > 200:
            raise serializers.ValidationError("Можно указать до 200 тегов.")
        if any(not key.isdecimal() or int(key) <= 0 for key in value):
            raise serializers.ValidationError("Ключи тегов должны быть положительными ID.")
        return {str(int(key)): count for key, count in value.items()}


class TrainingDraftView(BoundedTrainingView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, exam_id):
        exam = get_object_or_404(ExamVersion, pk=exam_id)
        return Response(builder.draft_payload(builder.get_draft(request.user, exam)))

    def post(self, request, exam_id):
        exam = get_object_or_404(ExamVersion, pk=exam_id)
        serializer = DraftInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            return Response(builder.change_draft(request.user, exam, serializer.validated_data))
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc


class ExamWorksView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, exam_id):
        exam = get_object_or_404(ExamVersion, pk=exam_id)
        return Response(builder.works_payload(request.user, exam, page=request.query_params.get("page", 1),
                                             exam_page=request.query_params.get("exam_page", 1)))


class WorkArchiveView(BoundedTrainingView):
    permission_classes = [permissions.IsAuthenticated]

    class Input(serializers.Serializer):
        archived = serializers.BooleanField()
        lifecycle_revision = serializers.IntegerField(min_value=0)
        operation_id = serializers.UUIDField()

    def post(self, request, attempt_id):
        serializer = self.Input(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(builder.archive_work(request.user, attempt_id, **serializer.validated_data))


class TrainingStateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, attempt_id):
        from django.urls import reverse
        work = get_object_or_404(VariantAttempt.objects.select_related("assignment__template"),
                                 pk=attempt_id, assignment__user=request.user, mode="training")
        exam = work.assignment.template.exam_version
        current_id = builder.lifecycle.current_training(request.user, exam).values_list("pk", flat=True).first()
        return Response({"archived": bool(work.archived_at or work.completed_at), "training_revision": work.training_revision,
                         "lifecycle_revision": builder.get_draft(request.user, exam).lifecycle_revision,
                         "current_attempt_id": current_id,
                         "current_url": reverse("accounts:variant-attempt-solver", args=[current_id]) if current_id else None})


class TrainingTaskCheckView(TrainingMutationView):
    permission_classes = [permissions.IsAuthenticated]

    class Input(serializers.Serializer):
        answer = serializers.JSONField()
        submission_key = serializers.UUIDField()

        def validate_answer(self, value):
            if variants.answer_is_blank(value):
                raise serializers.ValidationError("Введите ответ перед проверкой.")
            return value

    def post(self, request, attempt_id, variant_task_id):
        get_object_or_404(VariantAttempt, pk=attempt_id, assignment__user=request.user, mode="training")
        serializer = self.Input(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Save and score are one transaction; repeated requests reuse the submission key.
        from django.db import transaction
        with transaction.atomic():
            work = get_object_or_404(VariantAttempt.objects.select_for_update(), pk=attempt_id, assignment__user=request.user, mode="training")
            fingerprint = builder.lifecycle.operation_fingerprint({"check":attempt_id, "task":variant_task_id,
                                                                  "answer":serializer.validated_data["answer"]})
            key = serializer.validated_data["submission_key"]
            if builder.lifecycle.replay(request.user, key, fingerprint) is not None:
                return Response(VariantAttemptSerializer(variants.get_attempt_with_prefetch(request.user, attempt_id), context={"request":request}).data)
            previous = work.task_attempts.filter(submission_key=serializer.validated_data["submission_key"]).first()
            if previous:
                if previous.variant_task_id != variant_task_id or previous.task_snapshot.get("response", {}).get("value") != serializer.validated_data["answer"]:
                    raise serializers.ValidationError("Ключ отправки уже использован для другого ответа.")
                return Response(VariantAttemptSerializer(variants.get_attempt_with_prefetch(request.user, attempt_id), context={"request": request}).data)
            previous_check = work.task_attempts.filter(variant_task_id=variant_task_id, attempt_number__gt=0).order_by("-attempt_number").first()
            if previous_check and previous_check.task_snapshot.get("response", {}).get("value") == serializer.validated_data["answer"]:
                # Returning from the archive and pressing Check again is not a new observation.
                variants.save_task_response(request.user, attempt_id, variant_task_id, answer=serializer.validated_data["answer"])
                builder.lifecycle.receipt(request.user, key, fingerprint, {"check_id":previous_check.pk})
                return Response(VariantAttemptSerializer(variants.get_attempt_with_prefetch(request.user, attempt_id), context={"request": request}).data)
            variants.save_task_response(request.user, attempt_id, variant_task_id, answer=serializer.validated_data["answer"])
            result = variants.submit_task_answer(request.user, attempt_id, variant_task_id, is_correct=False,
                                        task_snapshot={"value": serializer.validated_data["answer"]},
                                        submission_key=serializer.validated_data["submission_key"])
            builder.lifecycle.receipt(request.user, key, fingerprint, {"check_id":result.task_attempt.pk})
            variants.set_active_task(request.user, attempt_id, variant_task_id)
        attempt = variants.get_attempt_with_prefetch(request.user, attempt_id)
        return Response(VariantAttemptSerializer(attempt, context={"request": request}).data)


class TrainingTaskFlagView(TrainingMutationView):
    permission_classes = [permissions.IsAuthenticated]

    class Input(serializers.Serializer):
        flagged = serializers.BooleanField()

    def post(self, request, attempt_id, variant_task_id):
        from django.db import transaction
        serializer = self.Input(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            work = get_object_or_404(VariantAttempt.objects.select_for_update(), pk=attempt_id, assignment__user=request.user, mode="training")
            variants._ensure_active_attempt(work)
            variants._validate_variant_task(work.assignment, variant_task_id, attempt=work)
            ids = set(work.flagged_task_ids)
            if serializer.validated_data["flagged"]:
                ids.add(variant_task_id)
            else:
                ids.discard(variant_task_id)
            work.flagged_task_ids = sorted(ids)
            work.save(update_fields=["flagged_task_ids", "updated_at"])
        return Response({"flagged_task_ids": work.flagged_task_ids})


class TrainingPauseView(TrainingMutationView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, attempt_id):
        from django.db import transaction
        with transaction.atomic():
            work = get_object_or_404(VariantAttempt.objects.select_for_update(), pk=attempt_id, assignment__user=request.user, mode="training")
            variants._stop_active_task_timer(work, reason="auto")
        return Response({"ok": True})
