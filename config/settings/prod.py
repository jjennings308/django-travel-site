from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403

DEBUG = False


def _required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"{name} must be set in the environment (.env) for production.")
    return value


def _flag(name, default):
    return os.environ.get(name, default).lower() in ("true", "1", "yes")


SECRET_KEY = _required("DJANGO_SECRET_KEY")
if SECRET_KEY.startswith("django-insecure") or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY is a placeholder or too short; generate a real one.")

ALLOWED_HOSTS = [h.strip() for h in _required("DJANGO_ALLOWED_HOSTS").split(",") if h.strip()]
# Origins that may POST forms, e.g. "https://staging.sharebucketlist.com".
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

SITE_URL = os.environ.get("SITE_URL", "https://www.sharebucketlist.com")

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

# --- HTTPS behind nginx -------------------------------------------------------
# nginx terminates TLS and sets X-Forwarded-Proto; trusting it makes
# request.is_secure() true, so the redirect below cannot loop. nginx must
# overwrite (not pass through) that header from clients.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = _flag("SECURE_SSL_REDIRECT", "True")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# Start low on a new domain: browsers remember HSTS for this long. Raise to
# 31536000 (a year) once HTTPS is known-good, and only then consider preload.
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "3600"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = _flag("SECURE_HSTS_INCLUDE_SUBDOMAINS", "False")
SECURE_HSTS_PRELOAD = False
# Deliberately off until HTTPS has run cleanly on the real domain: both are
# cached by browsers for the HSTS lifetime and preload is near-impossible to undo.
# Enable them (and remove these silences) when moving from staging to production.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]

# --- Logging ---------------------------------------------------------------------
# To stderr: under systemd that lands in the journal
# (journalctl -u travel_site). Errors include tracebacks.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
