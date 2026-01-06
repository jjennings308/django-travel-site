from .base import *

try:
    import django_extensions  # noqa: F401
    INSTALLED_APPS += ["django_extensions"]
except ImportError:
    pass

DEBUG = True

SITE_URL = "http://127.0.0.1:8000"

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"