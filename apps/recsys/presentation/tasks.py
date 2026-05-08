from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from bs4 import BeautifulSoup

from apps.recsys.models import Task, TaskAttachment, resolve_media_url
from apps.recsys.utils.rendering import render_task_body


def _image_attachments(task: Task | None) -> list[TaskAttachment]:
    if task is None:
        return []
    return [
        attachment
        for attachment in task.attachments.all()
        if attachment.kind == TaskAttachment.Kind.IMAGE
    ]


def _attachment_url(attachment: TaskAttachment) -> str:
    try:
        return resolve_media_url(attachment.file.url)
    except Exception:
        return ""


def _first_task_image_url(task: Task | None) -> str:
    if task is None:
        return ""
    if getattr(task, "image", None):
        try:
            return resolve_media_url(task.image.url)
        except Exception:
            pass
    for attachment in _image_attachments(task):
        url = _attachment_url(attachment)
        if url:
            return url
    return ""


def _replace_inline_data_images(task_body_html: str, image_urls: list[str]) -> tuple[str, bool]:
    if not task_body_html or not image_urls:
        return task_body_html, False

    soup = BeautifulSoup(task_body_html, "html.parser")
    changed = False
    image_index = 0
    for image in soup.find_all("img"):
        src = str(image.get("src") or "")
        if not src.startswith("data:image/"):
            continue
        if image_index >= len(image_urls):
            break
        image["src"] = image_urls[image_index]
        image_index += 1
        changed = True
    if not changed:
        return task_body_html, False
    return str(soup).strip().replace("<br/>", "<br>"), True


def _has_inline_image(task_body_html: str) -> bool:
    if not task_body_html:
        return False
    soup = BeautifulSoup(task_body_html, "html.parser")
    return soup.find("img") is not None


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
    image_attachment_urls = [
        url
        for url in (_attachment_url(attachment) for attachment in _image_attachments(task))
        if url
    ]

    attachments = source.get("attachments")
    if not isinstance(attachments, list):
        attachments = build_task_attachments_payload(task)

    task_body_html = render_task_body(description, rendering_strategy) if description else ""
    task_body_html, _ = _replace_inline_data_images(
        task_body_html,
        image_attachment_urls,
    )

    image = source.get("image") or content_payload.get("image") or ""
    if not image and not _has_inline_image(task_body_html):
        image = _first_task_image_url(task)

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
