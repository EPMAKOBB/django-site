import json
from django.contrib.auth import get_user_model
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from .models import Attempt, Task, SkillMastery
from .recommendation import recommend_tasks


@require_http_methods(["POST"])
def attempts_view(request):
    data = json.loads(request.body)
    user = get_object_or_404(get_user_model(), id=data["user"])
    task = get_object_or_404(Task, id=data["task"])
    attempt = Attempt.objects.create(user=user, task=task, is_correct=data.get("is_correct", False))
    return JsonResponse({"id": attempt.id}, status=201)


@require_http_methods(["GET"])
def next_task_view(request):
    user_id = request.GET.get("user")
    if not user_id:
        raise Http404("user parameter is required")
    user = get_object_or_404(get_user_model(), id=user_id)
    tasks = recommend_tasks(user)
    if not tasks:
        return JsonResponse({}, status=404)
    task = tasks[0]
    return JsonResponse({"id": task.id, "title": task.title})


@require_http_methods(["GET"])
def progress_view(request):
    user_id = request.GET.get("user")
    if not user_id:
        raise Http404("user parameter is required")
    user = get_object_or_404(get_user_model(), id=user_id)
    masteries = SkillMastery.objects.filter(user=user).order_by("skill__name")
    skills = [
        {"skill": sm.skill.name, "mastery": sm.mastery, "confidence": sm.confidence}
        for sm in masteries
    ]
    return JsonResponse({"skills": skills})
