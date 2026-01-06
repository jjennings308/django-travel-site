from .base import *

DEBUG = False

SITE_URL = "https://www.sharebucketlist.com"

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

EMAIL_HOST = "smtp.yourprovider.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = "smtp-user"
EMAIL_HOST_PASSWORD = "smtp-password"
