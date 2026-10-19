"""Per-account storage limit for uploads (site roadmap R15): photos, pictures, and anything a higher
app registers (trips registers its ticket files from its ``ready()``, so this app imports nothing
above it).

Upload helpers call ``check(user, incoming_bytes)`` *before* saving anything; it raises
``QuotaExceeded`` with a message for the person. ``apps.media_app.middleware.QuotaMiddleware`` turns
that into a message and a trip back to the page, so views don't each need handling. Staff are
unlimited.
"""
from django.conf import settings
from django.db.models import Sum

_providers = []


class QuotaExceeded(Exception):
    """Raised before an upload that would go over the account's limit; ``str()`` is for people."""


def register(fn):
    """``fn(user) -> bytes`` adds another kind of upload to the account's total."""
    if fn not in _providers:
        _providers.append(fn)
    return fn


def limit_bytes():
    return int(getattr(settings, "STORAGE_LIMIT_MB", 1024)) * 1024 * 1024


def used(user):
    from .models import Media
    total = Media.objects.filter(uploaded_by=user).aggregate(total=Sum("file_size"))["total"] or 0
    return total + sum(fn(user) for fn in _providers)


def size_of(files):
    return sum(getattr(f, "size", 0) or 0 for f in files if f)


def _gb(n):
    return f"{n / (1024 ** 3):.1f} GB" if n >= 1024 ** 3 else f"{max(1, round(n / (1024 ** 2)))} MB"


def check(user, incoming):
    """Raise ``QuotaExceeded`` if ``incoming`` more bytes would take ``user`` over the limit."""
    if user is None or not getattr(user, "is_authenticated", False) or user.is_staff or user.is_superuser:
        return
    have, cap = used(user), limit_bytes()
    if have + incoming > cap:
        raise QuotaExceeded(f"Not uploaded: you've used {_gb(have)} of your {_gb(cap)} for photos and tickets. "
                            "Remove some first, then try again.")
