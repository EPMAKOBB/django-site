from __future__ import annotations

import logging

from django.core.cache import cache
from django.utils import timezone

from .services import refresh_student_recsys_state

logger = logging.getLogger("recsys")


class RecsysDailyRefreshMiddleware:
    """
    Refresh student-side recsys state once per day on the first authenticated request.

    This keeps forgetting and type aggregates reasonably fresh even when there is no
    external scheduler configured yet.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            self._refresh_if_needed(user)
        return self.get_response(request)

    def _refresh_if_needed(self, user) -> None:
        today = timezone.localdate().isoformat()
        cache_key = f"recsys:daily-refresh:{user.pk}:{today}"
        if not cache.add(cache_key, 1, timeout=86400):
            return
        try:
            refresh_student_recsys_state(user, now=timezone.now())
        except Exception:
            cache.delete(cache_key)
            logger.exception("Failed to refresh daily recsys state", extra={"user_id": user.pk})
