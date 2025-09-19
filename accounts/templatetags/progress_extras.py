from __future__ import annotations

from django import template

register = template.Library()


@register.filter
def get_item(d: dict, key):
    try:
        return d.get(key)
    except Exception:
        return None


@register.filter
def mul(value, factor):
    try:
        return float(value) * float(factor)
    except Exception:
        return 0

