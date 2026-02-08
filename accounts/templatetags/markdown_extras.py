from __future__ import annotations

from django import template
from django.utils.safestring import mark_safe

import markdown

from apps.recsys.utils.rendering import render_task_body as _render_task_body
from apps.recsys.utils.sanitize import sanitize_html

register = template.Library()

_MARKDOWN_EXTENSIONS = [
    "markdown.extensions.extra",
    "markdown.extensions.md_in_html",
    "markdown.extensions.sane_lists",
]


@register.filter(name="render_markdown")
def render_markdown(value: str | None) -> str:
    if not value:
        return ""

    html = markdown.markdown(
        value,
        extensions=_MARKDOWN_EXTENSIONS,
        output_format="html5",
    )
    return mark_safe(sanitize_html(html))


@register.filter(name="render_task_body")
def render_task_body(value: str | None, rendering_strategy: str | None) -> str:
    return _render_task_body(value, rendering_strategy)
