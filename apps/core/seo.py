"""Search-engine and link-preview basics (site roadmap R22).

Views pass ``seo=meta(...)`` to their template; ``templates/partials/_seo.html`` (in both base
templates) writes the description, canonical link, Open Graph and Twitter-card tags, an optional
``noindex`` and optional JSON-LD from it, falling back to the site's name, tagline and share picture.
Each app builds its own JSON-LD (``<app>/seo.py``); this module only knows URLs and text.
"""
import re

from django.conf import settings
from django.templatetags.static import static
from django.utils.html import strip_tags

DEFAULT_IMAGE = "core/branding/png/sbl-logo-hero-2400x1200.png"
DESCRIPTION_CHARS = 160


def absolute(url):
    """``url`` on the site's public address (``SITE_URL``); full URLs pass through."""
    if not url or re.match(r"^https?://", url):
        return url or ""
    return settings.SITE_URL.rstrip("/") + "/" + url.lstrip("/")


def default_image():
    return absolute(static(DEFAULT_IMAGE))


def media_url(media):
    """A picture's absolute URL (images only), else ""."""
    if media is None or getattr(media, "media_type", "image") != "image" or not getattr(media, "file", None):
        return ""
    try:
        return absolute(media.file.url)
    except ValueError:
        return ""


def describe(*texts, limit=DESCRIPTION_CHARS):
    """The first non-empty text, tags stripped, whitespace collapsed, cut at a word near ``limit``."""
    for text in texts:
        text = " ".join(strip_tags(text or "").split())
        if text:
            if len(text) <= limit:
                return text
            return text[:limit - 1].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    return ""


def meta(title="", description="", image="", kind="website", jsonld=None, noindex=False):
    """What ``_seo.html`` needs for one page."""
    return {"title": title, "description": describe(description), "image": image, "type": kind,
            "jsonld": jsonld, "noindex": noindex}
