"""Photo/text submissions shared by training, EGE and OGE exam works."""
from copy import deepcopy
from io import BytesIO
import warnings
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.recsys.models import (WrittenSolution, SolutionPhoto, SolutionAssessment,
    VariantAttempt, VariantTaskAttempt, TaskType)
from . import variants

MAX_PHOTOS = 12
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def lock_owner(user):
    get_user_model().objects.select_for_update().get(pk=user.pk)


@transaction.atomic
def get_solution(user, attempt_id, task_id):
    lock_owner(user)
    attempt = VariantAttempt.objects.select_for_update().select_related('assignment__template').get(
        pk=attempt_id, assignment__user=user)
    task = variants._validate_variant_task(attempt.assignment, task_id, attempt=attempt)
    snapshot = variants._get_generated_snapshot(attempt, task)
    if not snapshot:
        raise ValidationError('Сначала откройте задание в работе.')
    if snapshot.get('scoring_scheme') != TaskType.ScoringScheme.MANUAL_SCALED:
        raise ValidationError('Для этого задания используется автоматическая проверка.')
    reference = deepcopy(snapshot)
    # Older issued tasks did not contain these fields. Freeze their references
    # once here; never replace a saved reference after an author edits the bank.
    reference.setdefault('reference_solution', task.task.reference_solution)
    reference.setdefault('assessment_criteria', task.task.assessment_criteria)
    solution, _ = WrittenSolution.objects.get_or_create(variant_attempt=attempt,
        variant_task=task, defaults={'reference_snapshot': reference})
    return solution


def ensure_editable(solution):
    if solution.submitted_at:
        raise ValidationError('Решение уже отправлено: его содержание зафиксировано.')
    attempt = solution.variant_attempt
    if attempt.completed_at or attempt.archived_at:
        raise ValidationError('Работа завершена или находится в архиве.')
    variants._ensure_time_limit_allows_submission(attempt)


def prepare_photo(upload):
    if upload.size > MAX_IMAGE_BYTES:
        raise ValidationError('Каждое фото должно быть не больше 10 МБ.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(upload) as source:
                if source.format not in ('JPEG', 'PNG', 'WEBP'):
                    raise ValidationError('Поддерживаются JPEG, PNG и WebP. Сохраните HEIC как JPEG.')
                if source.width * source.height > 32_000_000:
                    raise ValidationError('Разрешение фото слишком большое (максимум 32 Мп).')
                source.load()
                image = ImageOps.exif_transpose(source).convert('RGB')
                image.thumbnail((2600, 2600))
                output = BytesIO()
                image.save(output, 'JPEG', quality=90)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValidationError('Не удалось прочитать изображение. Выберите фото JPEG, PNG или WebP.') from exc
    return ContentFile(output.getvalue(), name='solution.jpg')


def add_photos(solution, uploads):
    """Caller locks the solution. Validate the whole batch before writing files."""
    ensure_editable(solution)
    count = solution.photos.count()
    if not uploads or count + len(uploads) > MAX_PHOTOS:
        raise ValidationError('Можно прикрепить от 1 до 12 фотографий на задание.')
    prepared = [prepare_photo(upload) for upload in uploads]
    saved = []
    try:
        for offset, content in enumerate(prepared):
            photo = SolutionPhoto(solution=solution, order=count + offset)
            photo.image.save(content.name, content, save=False)
            saved.append((photo.image.storage, photo.image.name))
            photo.save()
    except Exception:
        for storage, name in saved:
            storage.delete(name)
        raise


def edit_photo(solution, photo_id, action):
    ensure_editable(solution)
    photo = solution.photos.get(pk=photo_id)
    if action == 'delete':
        photo.delete()
    elif action == 'rotate':
        with photo.image.open('rb') as source:
            with Image.open(source) as image:
                output = BytesIO()
                image.rotate(-90, expand=True).save(output, 'JPEG', quality=90)
        storage, old = photo.image.storage, photo.image.name
        photo.image.save('rotated.jpg', ContentFile(output.getvalue()), save=True)
        transaction.on_commit(lambda: storage.delete(old))
    elif action in ('up', 'down'):
        photos = list(solution.photos.all())
        index = next(i for i, item in enumerate(photos) if item.pk == photo.pk)
        target = index + (-1 if action == 'up' else 1)
        if 0 <= target < len(photos):
            photos[index], photos[target] = photos[target], photos[index]
        for order, item in enumerate(photos):
            if item.order != order:
                item.order = order
                item.save(update_fields=['order', 'updated_at'])


def submit(solution, user, text):
    if solution.submitted_at:
        return  # A repeated browser submission is idempotent.
    ensure_editable(solution)
    text = text.strip()
    if len(text) > 30000:
        raise ValidationError('Комментарий должен быть не длиннее 30000 символов.')
    if not text and not solution.photos.exists():
        raise ValidationError('Прикрепите фото решения или введите решение текстом.')
    marker = {'written_solution_id': solution.pk}
    variants.save_task_response(user, solution.variant_attempt_id, solution.variant_task_id, answer=marker)
    result = variants.submit_task_answer(user, solution.variant_attempt_id, solution.variant_task_id,
        is_correct=False, task_snapshot={'value': marker})
    solution.text = text
    solution.task_attempt = result.task_attempt
    solution.submitted_at = timezone.now()
    solution.upload_key = uuid4()
    solution.save(update_fields=['text', 'task_attempt', 'submitted_at', 'upload_key', 'updated_at'])


def can_reveal(solution):
    return bool(solution.submitted_at and (
        solution.variant_attempt.mode == VariantAttempt.Mode.TRAINING or solution.variant_attempt.completed_at))


def reveal(solution):
    if not can_reveal(solution):
        raise ValidationError('Сначала отправьте решение. В пробнике критерии открываются после завершения всей работы.')
    if not solution.revealed_at:
        solution.revealed_at = timezone.now()
        solution.save(update_fields=['revealed_at', 'updated_at'])


def self_assess(solution, user, raw_score, comment):
    if not solution.revealed_at or not can_reveal(solution):
        raise ValidationError('Сначала откройте образец и критерии.')
    if not solution.reference_snapshot.get('assessment_criteria', '').strip():
        raise ValidationError('Автор пока не добавил критерии. Самооценка по критериям недоступна.')
    try:
        score = int(raw_score)
    except (ValueError, TypeError) as exc:
        raise ValidationError('Выберите целое число баллов.') from exc
    maximum = int(solution.reference_snapshot['max_score'])
    if str(score) != str(raw_score) or not 0 <= score <= maximum:
        raise ValidationError('Баллы должны быть целым числом от 0 до максимума задания.')
    if len(comment) > 3000:
        raise ValidationError('Комментарий должен быть не длиннее 3000 символов.')
    SolutionAssessment.objects.create(solution=solution, author=user,
        source=SolutionAssessment.Source.SELF, score=score, comment=comment)
    answer = VariantTaskAttempt.objects.select_for_update().get(pk=solution.task_attempt_id)
    answer.score = score
    answer.is_correct = score == maximum
    # Keep self-assessment in work results, but separate it from automatic
    # mastery/difficulty statistics. Every assessment has explicit provenance.
    answer.is_valid_attempt = False
    answer.save(update_fields=['score', 'is_correct', 'is_valid_attempt', 'updated_at'])
    variants.sync_variant_task_attempt_to_attempt(answer)
