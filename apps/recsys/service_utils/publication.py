from __future__ import annotations

from django.db.models import Count, Q, QuerySet

from apps.recsys.models import Task, VariantTemplate


def public_tasks_queryset(queryset: QuerySet[Task] | None = None) -> QuerySet[Task]:
    """Return tasks that are allowed on ordinary user-facing surfaces."""

    queryset = queryset if queryset is not None else Task.objects.all()
    return queryset.filter(status=Task.Status.PUBLISHED)


def task_is_public(task: Task | None) -> bool:
    return bool(task and task.status == Task.Status.PUBLISHED)


def with_publication_counts(queryset: QuerySet[VariantTemplate]) -> QuerySet[VariantTemplate]:
    return queryset.annotate(
        tasks_total=Count("template_tasks", distinct=True),
        unpublished_tasks_count=Count(
            "template_tasks",
            filter=~Q(template_tasks__task__status=Task.Status.PUBLISHED),
            distinct=True,
        ),
    )


def public_ready_variant_templates(queryset: QuerySet[VariantTemplate]) -> QuerySet[VariantTemplate]:
    """Return variant templates whose every task is published."""

    return with_publication_counts(queryset).filter(unpublished_tasks_count=0)


def variant_template_is_public_ready(template: VariantTemplate) -> bool:
    return not template.template_tasks.exclude(task__status=Task.Status.PUBLISHED).exists()
