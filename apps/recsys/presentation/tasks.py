from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from apps.recsys.models import Task, TaskAttachment, resolve_media_url
from apps.recsys.utils.rendering import render_task_body


def build_task_attachments_payload(task: Task | None) -> list[dict[str, Any]]:
    if task is None:
        return []

    attachments_payload: list[dict[str, Any]] = []
    for attachment in task.attachments.all():
        if attachment.kind != TaskAttachment.Kind.FILE:
            continue
        try:
            url = resolve_media_url(attachment.file.url)
        except Exception:
            continue
        name = attachment.download_name_override or Path(attachment.file.name).name
        attachments_payload.append(
            {
                "id": attachment.id,
                "name": name or "download",
                "label": attachment.label or "",
                "url": url,
            }
        )
    return attachments_payload


def build_task_statement_payload(
    *,
    task: Task | None = None,
    statement_source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source = statement_source if isinstance(statement_source, Mapping) else {}
    content = source.get("content")
    content_payload = content if isinstance(content, Mapping) else {}

    title = (
        source.get("title")
        or content_payload.get("title")
        or getattr(task, "title", "")
    )
    description = (
        source.get("description")
        or content_payload.get("statement")
        or getattr(task, "description", "")
        or ""
    )
    rendering_strategy = (
        source.get("rendering_strategy")
        or getattr(task, "rendering_strategy", None)
    )
    image = source.get("image")
    if not image and getattr(task, "image", None):
        image = resolve_media_url(task.image.url)

    attachments = source.get("attachments")
    if not isinstance(attachments, list):
        attachments = build_task_attachments_payload(task)

    task_body_html = render_task_body(description, rendering_strategy) if description else ""
    return {
        "title": title,
        "description": description,
        "task_body_html": task_body_html,
        "task_rendering_strategy": rendering_strategy,
        "image": image,
        "attachments": attachments,
    }


def build_task_presentation(
    *,
    task: Task | None = None,
    statement_source: Mapping[str, Any] | None = None,
    answer_schema: Mapping[str, Any] | None = None,
    max_score: int | None = None,
    task_type_name: str = "",
) -> dict[str, Any]:
    statement = build_task_statement_payload(task=task, statement_source=statement_source)
    return {
        "task_id": getattr(task, "id", None),
        "title": statement["title"],
        "task_body_html": statement["task_body_html"],
        "task_rendering_strategy": statement["task_rendering_strategy"],
        "image": statement["image"],
        "attachments": statement["attachments"],
        "answer_schema": answer_schema,
        "max_score": max_score,
        "task_type_name": task_type_name,
    }
