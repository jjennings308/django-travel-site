"""Error emails to ``settings.ADMINS`` (site roadmap R3), wired to ``django.request`` in prod.py.

Django's own ``AdminEmailHandler`` mails the request's POST data and every frame's local
variables, and here those can be passport or loyalty numbers. This handler sends only: the
exception type and where it happened (the subject), the method, path (no query string, which can
carry tokens), the user id, the time, and the traceback without local variables.

Flood guard: one email per distinct error (exception type + innermost file and line) per hour;
repeats only reach the journal (the console handler next to this one), and the next email for
that error says how many there were. The count lives in the ``alerts`` cache, a small file cache
in prod.py so both gunicorn workers share it (the default cache is per process).
"""
import hashlib
import logging
import traceback

from django.conf import settings
from django.core.cache import caches
from django.core.cache.backends.base import InvalidCacheBackendError
from django.core.mail import mail_admins
from django.utils import timezone

GUARD_SECONDS = 3600


def _cache():
    try:
        return caches["alerts"]
    except InvalidCacheBackendError:
        return caches["default"]


def signature(exc_type, tb):
    """(key, where) for an error: its type plus the innermost frame (file:line in function)."""
    frames = traceback.extract_tb(tb) if tb else []
    if frames:
        last = frames[-1]
        where = f"{last.filename.split('/apps/', 1)[-1] if '/apps/' in last.filename else last.filename}" \
                f":{last.lineno} ({last.name})"
    else:
        where = "unknown"
    name = exc_type.__name__ if exc_type else "Error"
    label = f"{name} at {where}"
    return "alert:" + hashlib.sha1(label.encode()).hexdigest(), label


def should_send(key):
    """True for the first occurrence of ``key`` in the guard window; counts the rest.
    Returns (send, repeats_since_last_email)."""
    cache = _cache()
    if cache.add(key, 0, GUARD_SECONDS):
        repeats = cache.get(f"{key}:missed", 0)
        cache.delete(f"{key}:missed")
        return True, repeats
    try:
        cache.incr(f"{key}:missed")
    except ValueError:
        cache.set(f"{key}:missed", 1, GUARD_SECONDS * 24)
    return False, 0


def body(record, request, repeats=0):
    lines = [record.getMessage(), ""]
    if request is not None:
        user = getattr(request, "user", None)
        user_id = getattr(user, "pk", None) if getattr(user, "is_authenticated", False) else None
        lines += [f"Method:  {request.method}", f"Path:    {request.path}", f"User id: {user_id or 'signed out'}"]
    lines.append(f"Time:    {timezone.now():%Y-%m-%d %H:%M:%S %Z}")
    if repeats:
        lines.append(f"Repeats: +{repeats} more since the last email about this error")
    if record.exc_info:
        lines += ["", "".join(traceback.format_exception(*record.exc_info))]  # no frame locals
    lines += ["", "POST data, the query string, cookies, headers and local variables are left out on purpose.",
              "More in the journal: journalctl -u travel_site"]
    return "\n".join(lines)


class AlertEmailHandler(logging.Handler):
    def emit(self, record):
        if not settings.ADMINS:
            return
        try:
            exc_type, _exc, tb = record.exc_info or (None, None, None)
            key, where = signature(exc_type, tb)
            send, repeats = should_send(key)
            if not send:
                return
            request = getattr(record, "request", None)
            subject = where if exc_type else record.getMessage()[:120]
            mail_admins(subject, body(record, request, repeats), fail_silently=True)
        except Exception:  # noqa: BLE001 - an alert must never raise inside the request that failed
            self.handleError(record)
