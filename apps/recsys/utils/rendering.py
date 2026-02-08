from __future__ import annotations

import markdown
from django.utils.html import linebreaks
from django.utils.safestring import mark_safe

from apps.recsys.models import Task
from apps.recsys.utils.sanitize import sanitize_html

_MARKDOWN_EXTENSIONS = [
    "markdown.extensions.extra",
    "markdown.extensions.md_in_html",
    "markdown.extensions.sane_lists",
]


def render_task_body(description: str | None, rendering_strategy: str | None) -> str:
    if not description:
        return ""
    if rendering_strategy == Task.RenderingStrategy.MARKDOWN:
        html = markdown.markdown(
            description,
            extensions=_MARKDOWN_EXTENSIONS,
            output_format="html5",
        )
        return mark_safe(sanitize_html(html))
    if rendering_strategy == Task.RenderingStrategy.HTML:
        return mark_safe(sanitize_html(description))
    return linebreaks(description)
