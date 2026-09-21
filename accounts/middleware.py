from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

from .models import DEFAULT_USER_TIMEZONE


class UserTimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        previous_timezone = timezone.get_current_timezone()
        timezone_name = DEFAULT_USER_TIMEZONE
        if getattr(request, "user", None) and request.user.is_authenticated:
            preferences = getattr(request.user, "preferences", None)
            if preferences:
                timezone_name = preferences.timezone
        try:
            timezone.activate(ZoneInfo(timezone_name))
        except (ZoneInfoNotFoundError, ValueError):
            timezone.activate(ZoneInfo(DEFAULT_USER_TIMEZONE))
        try:
            return self.get_response(request)
        finally:
            timezone.activate(previous_timezone)
