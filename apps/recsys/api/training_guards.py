from django.conf import settings
from django.db import transaction
from rest_framework import exceptions
from rest_framework.views import APIView

from apps.recsys.models import VariantAttempt
from apps.recsys.service_utils.training_lifecycle import ensure_writable, TrainingConflict, lock_user


class BoundedTrainingView(APIView):
    limit_training_attempts_only = False

    def initial(self, request, *args, **kwargs):
        size = len(request.body) if request.method == "POST" else 0
        super().initial(request, *args, **kwargs)
        oversized = size > getattr(settings, "TRAINING_REQUEST_MAX_BYTES", 65536)
        applies = not self.limit_training_attempts_only or (oversized and VariantAttempt.objects.filter(
            pk=kwargs.get("attempt_id"), assignment__user=request.user, mode="training").exists())
        if oversized and applies:
            raise exceptions.ValidationError("Запрос слишком большой. Уменьшите состав или размер ответа.")


class TrainingMutationView(BoundedTrainingView):
    """Keep the training version check and the mutation under the same row lock."""
    limit_training_attempts_only = True

    @transaction.atomic
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        attempt_id = kwargs.get("attempt_id")
        if not attempt_id or request.method != "POST":
            return
        if VariantAttempt.objects.filter(pk=attempt_id, assignment__user=request.user, mode="training").exists():
            lock_user(request.user)
        work = VariantAttempt.objects.select_for_update(of=("self",)).filter(pk=attempt_id, assignment__user=request.user).first()
        if work and work.mode == "training":
            raw = request.headers.get("X-Training-Revision")
            # Old clients are accepted only before the first archive transition.
            if raw is None and work.training_revision:
                raise TrainingConflict()
            try:
                revision = int(raw) if raw is not None else 0
            except (ValueError, TypeError):
                raise exceptions.ValidationError("Некорректная версия тренировки.")
            ensure_writable(work, revision)
            if request.path.endswith("/save/") and "expected_answer" in request.data:
                generation = work.task_attempts.filter(variant_task_id=kwargs.get("variant_task_id"), attempt_number=0).first()
                current_answer = (generation.task_snapshot or {}).get("response", {}).get("value") if generation else None
                if current_answer != request.data["expected_answer"]:
                    raise TrainingConflict("Ответ изменился в другой вкладке. Ваш вариант сохранён в браузере; выберите, какой оставить.")
