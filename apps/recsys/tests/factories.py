from __future__ import annotations

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
) -> Task:
    subject = subject or create_subject()
    task_type, _ = TaskType.objects.get_or_create(
        subject=subject,
        name=task_type_name,
        defaults={"description": ""},
    )
    title = title or f"Задание {uuid4()}"
    return Task.objects.create(
        subject=subject,
        type=task_type,
        title=title,
        description="",
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
    return VariantAttempt.objects.create(
        assignment=assignment,
        attempt_number=attempt_number,
    )


def add_task_attempt(
    *,
    variant_attempt: VariantAttempt,
    variant_task: VariantTask,
    attempt_number: int = 1,
    is_correct: bool = False,
    task_snapshot: dict | None = None,
) -> VariantTaskAttempt:
    return VariantTaskAttempt.objects.create(
        variant_attempt=variant_attempt,
        variant_task=variant_task,
        task=variant_task.task,
        attempt_number=attempt_number,
        is_correct=is_correct,
        task_snapshot=task_snapshot or {"title": variant_task.task.title},
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
