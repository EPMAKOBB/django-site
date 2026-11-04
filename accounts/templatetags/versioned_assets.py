"""Keep browser caches compatible with the current training API and templates."""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@lru_cache(maxsize=128)
def _fingerprint(filename, modified_ns, size):
    return sha256(Path(filename).read_bytes()).hexdigest()[:16]


@register.simple_tag
def versioned_static(path):
    url = static(path)
    source = finders.find(path)
    if not source:
        # Manifest-backed storage already supplies a content-specific URL.
        return url
    source = Path(source)
    info = source.stat()
    version = _fingerprint(str(source), info.st_mtime_ns, info.st_size)
    return f"{url}{'&' if '?' in url else '?'}v={version}"
