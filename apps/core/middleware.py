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

class UserThemeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        theme = "brand"

        user_theme = None
        if request.user.is_authenticated:
            s = getattr(request.user, "settings", None)
            user_theme = getattr(s, "theme", None) if s else None

        # Prefer DB theme if valid
        if user_theme in ("brand", "light", "dark"):
            theme = user_theme
        else:
            # Only fall back to cookie for anonymous / missing prefs
            cookie_theme = request.COOKIES.get("ui_theme")
            if cookie_theme in ("brand", "light", "dark"):
                theme = cookie_theme

        request.theme = theme
        response = self.get_response(request)

        # keep cookie synced with resolved theme
        response.set_cookie("ui_theme", theme, max_age=60 * 60 * 24 * 365)

        return response