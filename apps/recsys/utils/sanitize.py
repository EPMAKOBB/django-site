from __future__ import annotations

import bleach


_ALLOWED_TAGS = [
    "a",
    "b",
    "blockquote",
    "br",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "ul",
    "img",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "div",
    "span",
    "sub",
    "sup",
    "svg",
    "g",
    "path",
    "rect",
    "circle",
    "ellipse",
    "line",
    "polyline",
    "polygon",
    "text",
]

_ALLOWED_ATTRS = {
    "a": ["href", "title", "rel", "target"],
    "img": ["src", "alt", "title"],
    "th": ["colspan", "rowspan"],
    "td": ["colspan", "rowspan"],
    "div": ["class"],
    "span": ["class"],
    "svg": ["xmlns", "viewBox", "width", "height", "class", "aria-label", "role"],
    "g": ["class", "transform", "fill", "stroke", "stroke-width"],
    "path": ["class", "d", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin"],
    "rect": ["class", "x", "y", "width", "height", "rx", "ry", "fill", "stroke", "stroke-width"],
    "circle": ["class", "cx", "cy", "r", "fill", "stroke", "stroke-width"],
    "ellipse": ["class", "cx", "cy", "rx", "ry", "fill", "stroke", "stroke-width"],
    "line": ["class", "x1", "y1", "x2", "y2", "fill", "stroke", "stroke-width"],
    "polyline": ["class", "points", "fill", "stroke", "stroke-width"],
    "polygon": ["class", "points", "fill", "stroke", "stroke-width"],
    "text": ["class", "x", "y", "dx", "dy", "fill", "font-size", "text-anchor"],
}

_ALLOWED_PROTOCOLS = ["http", "https", "mailto", "data"]


def sanitize_html(value: str) -> str:
    return bleach.clean(
        value,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
    )

