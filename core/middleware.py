# core/middleware.py
from django.utils import timezone

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:
    ZoneInfo = None


class UserTimezoneMiddleware:
    """
    Activates the authenticated user's timezone (if available).
    Works for both public site and Django admin.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tzname = "UTC"

        if request.user.is_authenticated:
            # user.preferences may not exist yet; handle safely
            prefs = getattr(request.user, "preferences", None)
            tzname = getattr(prefs, "timezone", "UTC") if prefs else "UTC"

        if ZoneInfo:
            try:
                timezone.activate(ZoneInfo(tzname))
            except Exception:
                timezone.deactivate()
        else:
            # Fallback: if ZoneInfo isn't available for some reason
            timezone.deactivate()

        return self.get_response(request)
