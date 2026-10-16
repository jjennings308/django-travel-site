"""The trip booklet PDF (``trips:trip_pdf``): its own print-designed template rendered by
WeasyPrint, not a capture of the web page.

``booklet_context(trip)`` adds what a reader on paper needs to the trip page's prefetched
rows (no extra queries beyond the page's): each day's stay ("Staying: …", check-in / check-out),
its legs in order, and the at-a-glance rows for the cover. WeasyPrint needs the Pango and
HarfBuzz system libraries; ``render_pdf`` raises ``PdfUnavailable`` when they're missing so the
view can say so instead of failing with a 500.
"""


import re

# Pictographic emoji (💡, 🍺) and their variation selector: no emoji font is installed on the
# servers, so they'd print as empty boxes. Symbols the text font has (✈, →) are kept.
EMOJI = re.compile("[\U0001F000-\U0001FAFF\uFE0F]")


class PdfUnavailable(Exception):
    pass


def booklet_context(trip):
    stays = list(trip.lodging.all())
    days = list(trip.days.all())
    for day in days:
        day.stay = None
        day.checking_in = []
        day.checking_out = []
        if not day.date:
            continue
        for stay in stays:
            if stay.check_in <= day.date < stay.check_out:
                day.stay = stay
            if stay.check_in == day.date:
                day.checking_in.append(stay)
            if stay.check_out == day.date:
                day.checking_out.append(stay)
    open_tasks = [task for task in trip.booking_tasks.all() if not task.done]
    return {"days": days, "stays": stays, "open_tasks": open_tasks}


def render_pdf(html, base_url):
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:  # OSError: the Pango/HarfBuzz libraries are missing
        raise PdfUnavailable(str(exc)) from exc
    return HTML(string=EMOJI.sub("", html), base_url=base_url).write_pdf()
