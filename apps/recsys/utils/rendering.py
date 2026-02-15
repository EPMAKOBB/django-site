from __future__ import annotations

import markdown
import re
from django.utils.html import linebreaks
from django.utils.safestring import mark_safe

from apps.recsys.models import Task
from apps.recsys.utils.sanitize import sanitize_html

_MARKDOWN_EXTENSIONS = [
    "markdown.extensions.extra",
    "markdown.extensions.md_in_html",
    "markdown.extensions.sane_lists",
]

_MATH_PATTERNS = [
    re.compile(r"\$\$[\s\S]*?\$\$", re.MULTILINE),
    re.compile(r"\\\[[\s\S]*?\\\]", re.MULTILINE),
    re.compile(r"\\\([\s\S]*?\\\)"),
    re.compile(r"(?<!\$)\$(?!\$)(?:\\.|[^$\n\\])+(?<!\\)\$(?!\$)"),
]


def _protect_math_fragments(value: str) -> tuple[str, list[str]]:
    fragments: list[str] = []
    protected = value
    for pattern in _MATH_PATTERNS:
        def _replace(match: re.Match[str]) -> str:
            token = f"@@MATH_{len(fragments)}@@"
            fragments.append(match.group(0))
            return token

        protected = pattern.sub(_replace, protected)
    return protected, fragments


def _restore_math_fragments(value: str, fragments: list[str]) -> str:
    restored = value
    for index, fragment in enumerate(fragments):
        restored = restored.replace(f"@@MATH_{index}@@", fragment)
    return restored


def render_task_body(description: str | None, rendering_strategy: str | None) -> str:
    if not description:
        return ""
    if rendering_strategy == Task.RenderingStrategy.MARKDOWN:
        protected_description, math_fragments = _protect_math_fragments(description)
        html = markdown.markdown(
            protected_description,
            extensions=_MARKDOWN_EXTENSIONS,
            output_format="html5",
        )
        html = _restore_math_fragments(html, math_fragments)
        return mark_safe(sanitize_html(html))
    if rendering_strategy == Task.RenderingStrategy.HTML:
        return mark_safe(sanitize_html(description))
    return linebreaks(description)
