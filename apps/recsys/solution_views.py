"""Owner-only solution workspace and narrowly scoped temporary phone uploads."""
from io import BytesIO
from uuid import uuid4

from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import APIException

from .models import WrittenSolution, SolutionPhoto, VariantAttempt
from .service_utils import written_solutions as service

SALT = 'recsys.solution.phone-upload.v1'
TOKEN_AGE = 15 * 60


def private(response):
    # Keep a same-origin referrer for Django's HTTPS CSRF checks, while never
    # disclosing the phone token to an external destination.
    response['Referrer-Policy'] = 'same-origin'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def token_for(solution):
    return signing.dumps({'solution': solution.pk, 'key': str(solution.upload_key)}, salt=SALT)


def token_solution(token):
    try:
        data = signing.loads(token, salt=SALT, max_age=TOKEN_AGE)
        solution = WrittenSolution.objects.select_related('variant_attempt__assignment').get(
            pk=data['solution'], upload_key=data['key'], submitted_at__isnull=True)
        service.ensure_editable(solution)
        return solution
    except (signing.BadSignature, KeyError, ValueError, WrittenSolution.DoesNotExist,
            ValidationError, APIException) as exc:
        raise Http404('Ссылка истекла или решение уже отправлено. Откройте новую ссылку с компьютера.') from exc


def locked(solution):
    service.lock_owner(solution.variant_attempt.assignment.user)
    VariantAttempt.objects.select_for_update().get(pk=solution.variant_attempt_id)
    return WrittenSolution.objects.select_for_update().select_related(
        'variant_attempt__assignment__template', 'variant_task__task').get(pk=solution.pk)


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def workspace(request, attempt_id, task_id):
    try:
        solution = service.get_solution(request.user, attempt_id, task_id)
    except (VariantAttempt.DoesNotExist, ValidationError, APIException) as exc:
        raise Http404('Развёрнутое задание не найдено в вашей работе.') from exc
    error = None
    if request.method == 'POST':
        try:
            with transaction.atomic():
                solution = locked(solution)
                action = request.POST.get('action')
                if action == 'upload':
                    service.add_photos(solution, request.FILES.getlist('photos'))
                elif action in ('delete', 'rotate', 'up', 'down'):
                    try:
                        service.edit_photo(solution, int(request.POST.get('photo', '')), action)
                    except (ValueError, SolutionPhoto.DoesNotExist) as exc:
                        raise ValidationError('Фотография не найдена.') from exc
                elif action == 'save_text':
                    service.ensure_editable(solution)
                    text = request.POST.get('text', '').strip()
                    if len(text) > 30000:
                        raise ValidationError('Максимум 30000 символов.')
                    solution.text = text
                    solution.save(update_fields=['text', 'updated_at'])
                elif action == 'submit':
                    service.submit(solution, request.user, request.POST.get('text', solution.text))
                elif action == 'reveal':
                    service.reveal(solution)
                elif action == 'assess':
                    service.self_assess(solution, request.user, request.POST.get('score'), request.POST.get('comment', ''))
                elif action == 'revoke':
                    service.ensure_editable(solution)
                    solution.upload_key = uuid4()
                    solution.save(update_fields=['upload_key', 'updated_at'])
                else:
                    raise ValidationError('Неизвестное действие.')
            return redirect('written-solution', attempt_id, task_id)
        except (ValidationError, APIException) as exc:
            error = ' '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc.detail)
    solution.refresh_from_db()
    editable = True
    try:
        service.ensure_editable(solution)
    except (ValidationError, APIException):
        editable = False
    reference = solution.reference_snapshot
    context = dict(solution=solution, error=error, editable=editable,
        can_reveal=service.can_reveal(solution), photos=solution.photos.all(),
        assessments=solution.assessments.select_related('author'),
        title=reference.get('title') or solution.variant_task.task.title,
        statement_html=reference.get('task_body_html', ''),
        max_score=reference['max_score'], score_choices=range(int(reference['max_score']) + 1),
        reference=reference if solution.revealed_at else None,
        return_url=reverse('written-solution-list', args=[attempt_id]))
    if editable:
        token = token_for(solution)
        context['phone_url'] = request.build_absolute_uri(reverse('solution-phone', args=[token]))
        context['qr_url'] = reverse('solution-qr', args=[solution.pk])
        context['local_only'] = request.get_host().split(':')[0] in ('localhost', '127.0.0.1', '[::1]')
    return private(render(request, 'recsys/written_solution.html', context))


@login_required
@never_cache
def solution_list(request, attempt_id):
    attempt = get_object_or_404(VariantAttempt.objects.select_related('assignment__template'),
        pk=attempt_id, assignment__user=request.user)
    from .service_utils.variants import build_tasks_progress
    rows = [row for row in build_tasks_progress(attempt) if row.get('solution_url')]
    solutions = {s.variant_task_id: s for s in attempt.written_solutions.prefetch_related('assessments')}
    for row in rows:
        row['solution'] = solutions.get(row['variant_task_id'])
    return private(render(request, 'recsys/written_solution_list.html', {'work': attempt, 'rows': rows}))


@login_required
@never_cache
def photo(request, photo_id):
    item = get_object_or_404(SolutionPhoto.objects.select_related('solution__variant_attempt__assignment'),
        pk=photo_id, solution__variant_attempt__assignment__user=request.user)
    return private(FileResponse(item.image.open('rb'), content_type='image/jpeg'))


@login_required
@never_cache
def qr(request, solution_id):
    import qrcode
    import qrcode.image.svg
    solution = get_object_or_404(WrittenSolution.objects.select_related('variant_attempt'),
        pk=solution_id, variant_attempt__assignment__user=request.user)
    try:
        service.ensure_editable(solution)
    except (ValidationError, APIException) as exc:
        raise Http404 from exc
    url = request.build_absolute_uri(reverse('solution-phone', args=[token_for(solution)]))
    output = BytesIO()
    qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=5).save(output)
    return private(HttpResponse(output.getvalue(), content_type='image/svg+xml'))


@never_cache
@require_http_methods(['GET', 'POST'])
def phone(request, token):
    solution = token_solution(token)
    error = None
    if request.method == 'POST':
        try:
            with transaction.atomic():
                solution = locked(solution)
                # Recheck after obtaining the lock: submit/revoke may have won a race.
                token_solution(token)
                service.add_photos(solution, request.FILES.getlist('photos'))
            return redirect('solution-phone', token)
        except (ValidationError, APIException) as exc:
            error = ' '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc.detail)
    return private(render(request, 'recsys/solution_phone.html', dict(
        solution=solution, token=token, photos=solution.photos.all(), error=error)))


@never_cache
def phone_photo(request, token, photo_id):
    solution = token_solution(token)
    item = get_object_or_404(solution.photos, pk=photo_id)
    return private(FileResponse(item.image.open('rb'), content_type='image/jpeg'))


@login_required
@never_cache
def status(request, solution_id):
    solution = get_object_or_404(WrittenSolution, pk=solution_id, variant_attempt__assignment__user=request.user)
    return private(JsonResponse({'photos': list(solution.photos.values_list('pk', flat=True)),
        'submitted': bool(solution.submitted_at)}))
