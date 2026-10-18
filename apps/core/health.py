"""``/healthz/`` for uptime monitors and deploy.sh (site roadmap R3).

200 "ok" when the database answers ``SELECT 1`` and the static manifest resolves the site's
stylesheet (a deploy whose collectstatic never ran fails here); 503 "unavailable" otherwise. No
login, no details in the body (they go to the log), never cached, and plain text so no page
template (or analytics script) loads.
"""
import logging

from django.contrib.staticfiles.storage import staticfiles_storage
from django.db import connection
from django.http import HttpResponse
from django.views.decorators.cache import never_cache

log = logging.getLogger(__name__)
STYLESHEET = "css/dist/styles.css"


def checks():
    """Name of the first failing check, or None."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # noqa: BLE001
        log.warning("healthz: database check failed", exc_info=True)
        return "database"
    try:
        staticfiles_storage.url(STYLESHEET)  # the manifest storage raises when it's missing
    except Exception:  # noqa: BLE001
        log.warning("healthz: static manifest check failed", exc_info=True)
        return "static"
    return None


@never_cache
def healthz(request):
    failed = checks()
    return HttpResponse("ok" if failed is None else "unavailable", status=200 if failed is None else 503,
                        content_type="text/plain")
