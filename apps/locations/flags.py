"""A country's flag as its picture (country-flags plan C1).

The PNGs in ``apps/locations/flags/<iso2>.png`` are flag-icons 7.2.3's 4:3 flags (MIT, ``flags/LICENSE``),
rendered at 1200 × 900 by the dev-only ``scripts/build_flag_pngs.py`` and committed, so production needs neither
Node nor cairo. ``attach(country)`` stores one as a public, staff-side ``Media`` image ("Flag of <name>", attached to
the country, no uploader) under ``site/flags/`` in the normal media storage, and makes it the country's
``flag_media`` and — unless it already has a picture (``replace``) — its ``featured_media``. A photo uploaded later
replaces the flag as the picture and leaves ``flag_media`` set, so the edit page can offer "Use the flag" again.

Not through ``media_app.quota`` (catalogue data, no uploader) nor ``shrink_image`` (already 1200 px wide).
"""
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.core.files import File
from django.core.files.storage import default_storage

FLAGS = Path(__file__).resolve().parent / "flags"
FLAG_TITLE = "Flag of {name}"


def png_for(country):
    """The committed PNG for a country's two-letter code, or None (``XK`` and the like have none)."""
    code = (country.iso_code or "").strip().lower()
    path = FLAGS / f"{code}.png"
    return path if len(code) == 2 and path.exists() else None


def _usable(media):
    return media is not None and media.file and default_storage.exists(media.file.name)


def flag_media(country):
    """The country's flag ``Media``: its ``flag_media`` while the file is still there, else a new one (None
    without a PNG)."""
    from apps.media_app.models import Media
    if country.flag_media_id and _usable(country.flag_media):
        return country.flag_media
    png = png_for(country)
    if png is None:
        return None
    with png.open("rb") as handle:
        name = default_storage.save(f"site/flags/{png.name}", File(handle))
    return Media.objects.create(
        file=name, media_type="image", width=1200, height=900, title=FLAG_TITLE.format(name=country.name)[:200],
        alt_text=FLAG_TITLE.format(name=country.name)[:200], uploaded_by=None, is_user_generated=False,
        privacy="public", content_type=ContentType.objects.get_for_model(country), object_id=country.pk)


def attach(country, replace=False):
    """Give ``country`` its flag: ``flag_media`` always, and ``featured_media`` when it has no picture (or with
    ``replace``, instead of the photo it has). Returns (media, what happened): "made", "reused", "replaced",
    "kept photo", "no png" or "off" (``COUNTRY_FLAGS_ENABLED`` is False, as in tests)."""
    from django.conf import settings
    if not getattr(settings, "COUNTRY_FLAGS_ENABLED", True):
        return None, "off"
    had_flag = country.flag_media_id is not None and _usable(country.flag_media)
    media = flag_media(country)
    if media is None:
        return None, "no png"
    photo = country.featured_media_id is not None and country.featured_media_id != media.pk
    fields = []
    if country.flag_media_id != media.pk:
        country.flag_media = media
        fields.append("flag_media")
    if country.featured_media_id is None or (photo and replace):
        country.featured_media = media
        fields.append("featured_media")
    if fields:
        country.save(update_fields=fields)
    if photo:
        return media, "replaced" if replace else "kept photo"
    return media, "reused" if had_flag else "made"
