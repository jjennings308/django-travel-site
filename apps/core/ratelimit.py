"""Per-visitor rate limits for the doors abuse comes through (site roadmap R15).

``limit(scope, max_hits, window_seconds)`` decorates a view: past ``max_hits`` requests (of the
given methods) from one visitor IP in ``window_seconds``, it answers 429 with a plain "try again in N
minutes" page that says nothing about any account. ``hit()`` is the same check for code that only
counts some requests (a wrong sign-up code). Counts live in the ``ratelimit`` cache (a file cache in
prod.py, shared by the gunicorn workers), else the default cache.

The IP is nginx's ``X-Real-IP`` (it always sets it from the real connection), else ``REMOTE_ADDR``.
"""
import math
import time
from functools import wraps

from django.core.cache import caches
from django.core.cache.backends.base import InvalidCacheBackendError
from django.shortcuts import render


def _cache():
    try:
        return caches["ratelimit"]
    except InvalidCacheBackendError:
        return caches["default"]


def client_ip(request):
    return (request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or "unknown").strip()


def hit(request, scope, max_hits, window):
    """Count one request; True while within the limit, else (False, seconds to wait).
    ``RATELIMIT_ENABLED = False`` (the test settings) turns every limit off."""
    from django.conf import settings
    if not getattr(settings, "RATELIMIT_ENABLED", True):
        return True, 0
    bucket = int(time.time() // window)
    key = f"rl:{scope}:{client_ip(request)}:{bucket}"
    cache = _cache()
    cache.add(key, 0, window + 5)
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, window + 5)
        count = 1
    if count > max_hits:
        return False, window - (time.time() % window)
    return True, 0


def too_many(request, wait_seconds):
    minutes = max(1, math.ceil(wait_seconds / 60))
    response = render(request, "core/too_many.html", {"minutes": minutes}, status=429)
    response["Retry-After"] = str(int(wait_seconds))
    return response


def limit(scope, max_hits, window, methods=("POST",)):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method in methods:
                allowed, wait = hit(request, scope, max_hits, window)
                if not allowed:
                    return too_many(request, wait)
            return view(request, *args, **kwargs)
        return wrapped
    return decorator
