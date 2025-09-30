from __future__ import annotations

from django import template
from django.utils.safestring import mark_safe

import markdown

register = template.Library()

_MARKDOWN_EXTENSIONS = [
    "markdown.extensions.extra",
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
    return mark_safe(html)
