from __future__ import annotations

import html
import markdown
import re
from bs4 import BeautifulSoup
from django.utils.html import linebreaks
from django.utils.safestring import mark_safe

from apps.recsys.models import Task
from apps.recsys.utils.sanitize import sanitize_html

_MARKDOWN_EXTENSIONS = [
    "markdown.extensions.extra",
    "markdown.extensions.md_in_html",
    "markdown.extensions.sane_lists",
]

_FORM_TAGS = {"button", "form", "input", "select", "textarea"}
_CONTENT_TAGS = {
    "audio",
    "br",
    "canvas",
    "circle",
    "ellipse",
    "iframe",
    "img",
    "line",
    "path",
    "polygon",
    "polyline",
    "rect",
    "svg",
    "table",
    "text",
    "video",
}
_HTML_HINT_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "iframe",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "span",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}

_MATH_PATTERNS = [
    re.compile(r"\$\$[\s\S]*?\$\$", re.MULTILINE),
    re.compile(r"\\\[[\s\S]*?\\\]", re.MULTILINE),
    re.compile(r"\\\([\s\S]*?\\\)"),
    re.compile(r"(?<!\$)\$(?!\$)(?:\\.|[^$\n\\])+(?<!\\)\$(?!\$)"),
]


def _decode_escaped_html(value: str) -> str:
    if not value or "&lt;" not in value or "&gt;" not in value:
        return value
    soup = BeautifulSoup(value, "html.parser")
    if soup.find(True):
        return value
    return html.unescape(value)


def _looks_like_html(value: str) -> bool:
    if not value:
        return False
    decoded = _decode_escaped_html(value)
    soup = BeautifulSoup(decoded, "html.parser")
    return soup.find(list(_HTML_HINT_TAGS)) is not None


def _render_html_body(value: str) -> str:
    return normalize_task_body_html(sanitize_html(_decode_escaped_html(value)))


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


def normalize_task_body_html(value: str | None) -> str:
    """Return canonical task-statement HTML shared by all task surfaces."""
    if not value:
        return ""

    soup = BeautifulSoup(str(value), "html.parser")
    for tag in soup.find_all(list(_FORM_TAGS)):
        if tag.name == "form":
            tag.unwrap()
        else:
            tag.decompose()

    changed = True
    while changed:
        changed = False
        for tag in list(soup.find_all(True)):
            if tag.find_parent("table"):
                continue
            if tag.name in _CONTENT_TAGS or tag.find(list(_CONTENT_TAGS)):
                continue
            if tag.get_text(strip=True):
                continue
            tag.decompose()
            changed = True

    return str(soup).strip().replace("<br/>", "<br>")


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
        return mark_safe(normalize_task_body_html(sanitize_html(html)))
    if rendering_strategy == Task.RenderingStrategy.HTML:
        return mark_safe(_render_html_body(description))
    if _looks_like_html(description):
        return mark_safe(_render_html_body(description))
    return mark_safe(normalize_task_body_html(linebreaks(description)))
