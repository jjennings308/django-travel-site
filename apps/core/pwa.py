"""The site as an installable, partly-offline web app (site roadmap R6).

``/sw.js`` serves ``core/sw.js`` from the site root (a worker can only control pages under the
folder its script comes from; the trip page registers it with scope ``/trips/``).
``/manifest.webmanifest`` lets phones add the site to the home screen. ``offline_cache_key``
names a person's offline cache without revealing who they are.
"""
import json

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import Http404, HttpResponse
from django.templatetags.static import static
from django.utils.crypto import salted_hmac
from django.views.decorators.cache import cache_control

_WORKER = None


def offline_cache_key(user):
    """A stable, opaque per-person cache name part (not the user id)."""
    return salted_hmac("sbl-offline-cache", str(user.pk)).hexdigest()[:20]


def _worker_source():
    global _WORKER
    if _WORKER is None or settings.DEBUG:
        path = finders.find("core/sw.js")
        if path is None:
            raise Http404
        with open(path, encoding="utf-8") as handle:
            _WORKER = handle.read()
    return _WORKER


@cache_control(no_cache=True, max_age=0)
def service_worker(request):
    response = HttpResponse(_worker_source(), content_type="application/javascript; charset=utf-8")
    response["Service-Worker-Allowed"] = "/trips/"
    return response


@cache_control(max_age=86400)
def manifest(request):
    data = {
        "name": settings.SITE_NAME,
        "short_name": settings.SITE_NAME,
        "description": getattr(settings, "SITE_TAGLINE", ""),
        "start_url": "/trips/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#faf8f5",
        "theme_color": "#9a4a2a",
        "icons": [
            {"src": static("core/branding/png/app/icon-192x192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": static("core/branding/png/app/icon-512x512.png"), "sizes": "512x512", "type": "image/png"},
        ],
    }
    return HttpResponse(json.dumps(data, indent=2), content_type="application/manifest+json")
