"""The trip booklet PDF (``trips:trip_pdf``): its own print-designed template rendered by
WeasyPrint, not a capture of the web page.

``booklet_context(trip)`` adds what a reader on paper needs to the trip page's prefetched
rows (no extra queries beyond the page's): each day's stay ("Staying: …", check-in / check-out,
from ``itinerary.attach_stays``; the legs per day come from ``itinerary.place_legs``, which the
view runs) and the open tasks for the reference pages. Items on a split group's track (day-first plan
P5) leave the day's own tables (``day.shared_legs`` / ``shared_activities`` / ``shared_meals``) and are
printed in their track. WeasyPrint needs the Pango and
HarfBuzz system libraries; ``render_pdf`` raises ``PdfUnavailable`` when they're missing so the
view can say so instead of failing with a 500.

The cover shows ``Trip.cover_photo`` when an editor chose one: ``cover_image`` embeds it as a ``data:`` URI
(scaled to ``COVER_SIDE`` px, JPEG), so WeasyPrint never fetches a private photo over HTTP.
"""


import base64
import io
import logging
import re

logger = logging.getLogger(__name__)

COVER_SIDE = 1800  # px, the longer side: sharp across a Letter page at print size, small enough to embed

# Pictographic emoji (💡, 🍺) and their variation selector: no emoji font is installed on the
# servers, so they'd print as empty boxes. Symbols the text font has (✈, →) are kept.
EMOJI = re.compile("[\U0001F000-\U0001FAFF\uFE0F]")


class PdfUnavailable(Exception):
    pass


def booklet_context(trip):
    from .itinerary import _shared, attach_stays, tracks
    stays = list(trip.lodging.all())
    days = list(trip.days.all())
    attach_stays(days, stays)
    for day in days:
        day.shared_legs = _shared(getattr(day, "day_legs", []))
        day.shared_activities = _shared(getattr(day, "ordered_activities", []))
        day.shared_meals = _shared(getattr(day, "ordered_meals", []))
        for group in getattr(day, "split_groups", []):
            tracks(group)
    open_tasks = [task for task in trip.booking_tasks.all() if not task.done]
    return {"days": days, "stays": stays, "open_tasks": open_tasks, "cover_image": cover_image(trip)}


def cover_image(trip):
    """The trip's cover photo as a JPEG ``data:`` URI, or "" (none chosen, or the file can't be read)."""
    media = trip.cover_photo if trip.cover_photo_id else None
    if media is None or not media.file:
        return ""
    from PIL import Image, ImageOps
    try:
        with media.file.open("rb") as f, Image.open(f) as picture:
            picture = ImageOps.exif_transpose(picture).convert("RGB")
            picture.thumbnail((COVER_SIDE, COVER_SIDE))
            out = io.BytesIO()
            picture.save(out, "JPEG", quality=85)
    except (OSError, ValueError) as exc:
        logger.warning("Trip %s: cover photo %s unreadable (%s)", trip.pk, media.pk, exc.__class__.__name__)
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def render_pdf(html, base_url):
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:  # OSError: the Pango/HarfBuzz libraries are missing
        raise PdfUnavailable(str(exc)) from exc
    return HTML(string=EMOJI.sub("", html), base_url=base_url).write_pdf()
