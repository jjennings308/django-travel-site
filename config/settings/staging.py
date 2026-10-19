"""staging.sharebucketlist.com (site roadmap R16): production settings, but it can never email anyone,
it says it's staging on every page, and search engines are told not to index it.

Its data is a nightly, disguised copy of production (scripts/sync_staging_from_prod.sh); nginx puts
the whole site behind basic auth (deploy/staging/). Set up from deploy/staging/README.md.
"""
from .prod import *  # noqa: F401,F403

STAGING = True
# Mail never leaves staging, whatever .env says: it's written to the journal instead.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
SITE_URL = os.environ.get("SITE_URL", "https://staging.sharebucketlist.com")  # noqa: F405
# A brand-new host: remember HTTPS for an hour only, as prod.py's own comment advises.
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "3600"))  # noqa: F405
MIDDLEWARE = [*MIDDLEWARE, "apps.core.middleware.NoIndexMiddleware"]  # noqa: F405

# Its own rate-limit and error-email counts: sharing production's /tmp folders would let a staging
# error silence the same error's email from production for an hour.
CACHES = {
    **CACHES,  # noqa: F405
    "alerts": {"BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
               "LOCATION": "/tmp/sharebucketlist-staging-alerts"},
    "ratelimit": {"BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
                  "LOCATION": "/tmp/sharebucketlist-staging-ratelimit"},
}
