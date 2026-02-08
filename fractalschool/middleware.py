import re
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.utils.timezone import now


@dataclass(frozen=True)
class RateLimitRule:
    key: str
    limit: int
    window_seconds: int


def _parse_rate(value: str) -> tuple[int, int]:
    """
    Parse strings like "5/15m", "120/m", "100/60s" into (limit, window_seconds).
    """
    match = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)?\s*([smhd])\s*", value)
    if not match:
        raise ValueError(f"Invalid rate limit value: {value}")

    limit = int(match.group(1))
    window = int(match.group(2) or 1)
    unit = match.group(3)
    unit_seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    return limit, window * unit_seconds


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _make_rules() -> tuple[RateLimitRule, dict[str, RateLimitRule]]:
    config = getattr(settings, "RATE_LIMITS", {})
    public_rate = config.get("public", "120/m")
    sensitive = config.get("sensitive", {})

    public_limit, public_window = _parse_rate(public_rate)
    public_rule = RateLimitRule("public", public_limit, public_window)

    sensitive_rules: dict[str, RateLimitRule] = {}
    for path, rate in sensitive.items():
        limit, window = _parse_rate(rate)
        sensitive_rules[path] = RateLimitRule(f"sensitive:{path}", limit, window)

    return public_rule, sensitive_rules


class RateLimitMiddleware:
    """
    Applies strict rate limiting to all public (unauthenticated) routes and
    aggressive limits to sensitive endpoints like /login and /register.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self._public_rule, self._sensitive_rules = _make_rules()

    def __call__(self, request):
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            path = request.path
            rule = self._sensitive_rules.get(path, self._public_rule)
            if not self._allow(request, rule):
                return JsonResponse(
                    {
                        "detail": "Rate limit exceeded. Try again later.",
                        "limit": rule.limit,
                        "window_seconds": rule.window_seconds,
                    },
                    status=429,
                )
        return self.get_response(request)

    def _allow(self, request, rule: RateLimitRule) -> bool:
        ip = _client_ip(request)
        window_key = int(now().timestamp() // rule.window_seconds)
        cache_key = f"rl:{rule.key}:{ip}:{window_key}"

        # Fast path: create key on first request.
        if cache.add(cache_key, 1, timeout=rule.window_seconds):
            return True

        try:
            count = cache.incr(cache_key)
        except ValueError:
            count = 1
            cache.set(cache_key, count, timeout=rule.window_seconds)

        return count <= rule.limit
