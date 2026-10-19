"""Settings for ``manage.py test`` (and CI): the dev settings minus what only slows tests down.

``manage.py`` picks this module for ``test`` when ``DJANGO_SETTINGS_MODULE`` isn't set; CI sets it
explicitly. Nothing here is ever used by a running site.
"""
from .base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
SITE_URL = "http://127.0.0.1:8000"

# Creating an account hashes its password, and the real hasher is deliberately slow; tests make
# hundreds of accounts. MD5 is fine for throwaway test users and never reaches production.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
GEOCODING_ENABLED = False  # never call OpenStreetMap from a test
RATELIMIT_ENABLED = False  # tests sign in hundreds of times; test_ratelimit turns it back on
