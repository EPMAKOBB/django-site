from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model

from apps.recsys.models import (
    Task,
    TaskType,
    VariantAssignment,
    VariantAttempt,
    VariantTask,
    VariantTaskAttempt,
    VariantTemplate,
)
from apps.recsys.service_utils import variants as variant_service
from subjects.models import Subject


def create_subject(name: str | None = None) -> Subject:
    name = name or f"Предмет {uuid4()}"
    subject, _ = Subject.objects.get_or_create(name=name)
    return subject


def create_task(
    *,
    subject: Subject | None = None,
    title: str | None = None,
    task_type_name: str = "Базовый тип",
    is_dynamic: bool = False,
    generator_slug: str = "",
    default_payload: dict | None = None,
    rendering_strategy: str | None = None,
    difficulty_level: int = 0,
    correct_answer: dict | None = None,
) -> Task:
    subject = subject or create_subject()
    task_type, _ = TaskType.objects.get_or_create(
        subject=subject,
        name=task_type_name,
        defaults={"description": ""},
    )
    title = title or f"Задание {uuid4()}"
    payload = deepcopy(default_payload) if default_payload else {}
    strategy = rendering_strategy or Task.RenderingStrategy.MARKDOWN
    return Task.objects.create(
        subject=subject,
        type=task_type,
        title=title,
        description="",
        is_dynamic=is_dynamic,
        generator_slug=generator_slug if is_dynamic else "",
        default_payload=payload,
        rendering_strategy=strategy,
        difficulty_level=difficulty_level,
        correct_answer=deepcopy(correct_answer) if correct_answer else {},
    )


def create_variant_template(
    *,
    name: str | None = None,
    time_limit_minutes: int | None = 60,
    max_attempts: int | None = 3,
) -> VariantTemplate:
    time_limit = (
        timedelta(minutes=time_limit_minutes) if time_limit_minutes is not None else None
    )
    return VariantTemplate.objects.create(
        name=name or f"Вариант {uuid4()}",
        time_limit=time_limit,
        max_attempts=max_attempts,
    )


def add_variant_task(
    *,
    template: VariantTemplate,
    task: Task,
    order: int = 1,
    max_attempts: int | None = None,
) -> VariantTask:
    return VariantTask.objects.create(
        template=template,
        task=task,
        order=order,
        max_attempts=max_attempts,
    )


def assign_variant(
    *,
    template: VariantTemplate,
    username: str | None = None,
    deadline=None,
) -> VariantAssignment:
    user_model = get_user_model()
    username = username or f"student_{uuid4()}"
    user, _ = user_model.objects.get_or_create(username=username)
    return VariantAssignment.objects.create(
        template=template,
        user=user,
        deadline=deadline,
    )


def start_attempt(
    *,
    assignment: VariantAssignment,
    attempt_number: int = 1,
) -> VariantAttempt:
    attempt = variant_service.start_new_attempt(assignment.user, assignment.id)
    if attempt.attempt_number != attempt_number:
        attempt.attempt_number = attempt_number
        attempt.save(update_fields=["attempt_number"])
    return attempt


def add_task_attempt(
    *,
    variant_attempt: VariantAttempt,
    variant_task: VariantTask,
    attempt_number: int = 1,
    is_correct: bool = False,
    task_snapshot: dict | None = None,
) -> VariantTaskAttempt:
    if task_snapshot is None:
        task_snapshot = {
            "task": {
                "type": "static",
                "task_id": variant_task.task_id,
                "title": variant_task.task.title,
                "description": variant_task.task.description,
                "rendering_strategy": variant_task.task.rendering_strategy,
            }
        }
    return VariantTaskAttempt.objects.create(
        variant_attempt=variant_attempt,
        variant_task=variant_task,
        task=variant_task.task,
        attempt_number=attempt_number,
        is_correct=is_correct,
        task_snapshot=deepcopy(task_snapshot),
    )


__all__ = [
    "create_subject",
    "create_task",
    "create_variant_template",
    "add_variant_task",
    "assign_variant",
    "start_attempt",
    "add_task_attempt",
]
