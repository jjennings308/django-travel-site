from .base import *

try:
    import django_extensions  # noqa: F401
    INSTALLED_APPS += ["django_extensions"]
except ImportError:
    pass

DEBUG = True

# Tailwind build tooling (manage.py tailwind build/start) is development-only, so the
# CSS can never be rebuilt on a production server. Production serves the committed
# theme/static/css/dist/styles.css via collectstatic.
INSTALLED_APPS += ["tailwind"]

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "web-dev", "192.168.10.150","travel.popsicletoes.us"]

SITE_URL = "http://127.0.0.1:8000"

#EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"


INTERNAL_IPS = [
    "127.0.0.1",
]

if DEBUG:
    INSTALLED_APPS += ['django_browser_reload']
    MIDDLEWARE += ['django_browser_reload.middleware.BrowserReloadMiddleware']