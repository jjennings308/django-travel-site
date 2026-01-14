from .base import *

try:
    import django_extensions  # noqa: F401
    INSTALLED_APPS += ["django_extensions"]
except ImportError:
    pass

DEBUG = True

SITE_URL = "http://127.0.0.1:8000"

#EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

EMAIL_HOST = "mail.smtp2go.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = "popsicletoes.us"
EMAIL_HOST_PASSWORD = "6AGTl8G6H5lktQfa"
