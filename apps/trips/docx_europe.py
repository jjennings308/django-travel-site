"""Parser for the Europe 2027 draft, which is not a Taos-shaped document.

The Taos original numbers its days (``Day 3 — Monday, September 14 — Theme``)
and hangs structured content off regular tables. The Europe draft shares
almost none of that: day headings are plain paragraphs reading
``Sat Sept 25  [All 6 → splits]  Fly to England``, sub-headings are bold text
rather than a heading style, and a single "Key Bookings" table carries the
whole outstanding-bookings list.

Rather than bolt ``or maybe`` branches onto the Taos walk, this is a separate
module. It is pure in the same way ``docx_import`` is: no Django, no database.

Two things about this document are worth stating up front, because they shape
what can be imported at all:

**Transport is not importable as ``TransportLeg`` rows.** Every leg table in
the draft gives a *duration* (``~45 min``, ``~2.5 hrs``), never a departure
time, and ``TransportLeg.departure_at`` is a required datetime. Inventing times
would be exactly the failure ``docx_import`` warns about elsewhere — a
plausible-looking guess that is silently hours wrong. The leg tables are
therefore kept as ``logistics_table`` sections, which loses nothing, and the
scheduled flights (described in the draft as "overnight flight", "~7–9am") are
reported as warnings rather than guessed.

**Rosters come from the Group Key table.** Each day heading carries a badge
like ``[Group of 4]``, and the ``Badge | Travelers | Leg | Notes`` table near
the top maps badges to actual names. That is the whole point of the badge: it
lets the document name a subset without repeating six names on every heading,
and it resolves cleanly onto ``Day.travelers``.
"""

import re
from datetime import date

from .docx_import import (
    EU_DAY_RE,
    ParsedTrip,
    _meal_type_from,
    _rows,
    _section,
    _to_date,
)

# A sub-heading is a short, fully-bold line. The draft also bolds the leading
# phrase of ordinary body paragraphs ("Hinkelstein — Markt 18, ... Opens 7pm
# Sunday"), so boldness alone is not enough; and length alone is not either,
# because "Windsor to LHR — The Easiest Airport Transfer of the Trip" is a real
# 57-character heading. The combination is close but not exact: it demotes
# "Afternoon — Light Augsburg Stroll (Travel Day — Keep It Easy)" to body text
# and promotes one descriptive line to a heading. Both are cosmetic and the
# prose survives either way, which is why a threshold is acceptable here and a
# structural rule is not.
SUBHEADING_MAX = 60

OPTION_LINE_RE = re.compile(r"^OPTION\s+([A-Z])\b[:\s]*(.*)$")
HOTEL_IN_HEADING_RE = re.compile(r"\s+Hotel\s+\d+:\s*(.+)$")
NAME_SPLIT_RE = re.compile(r"\s*,\s*|\s+&\s+|\s+and\s+")
DATE_RANGE_RE = re.compile(
    r"(?P<mon>[A-Za-z]+)\.?\s+(?P<day>\d{1,2})\s*[–—-]\s*"
    r"(?:(?P<mon2>[A-Za-z]+)\.?\s+)?(?P<day2>\d{1,2})"
)
PRIORITY_RE = re.compile(r"\b(critical|high|medium|low)\b", re.IGNORECASE)
MONTHS_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)", re.IGNORECASE
)
MEAL_HEADER = ("restaurant", "venue")
PRICE_PREFIX_RE = re.compile(r"^[€$£]")

# The Trip Overview keys this draft actually uses, and what each one feeds.
OVERVIEW_TO_NOTES = (
    "fly_in",
    "airline",
    "transport_germany",
    "hotels_germany",
    "hotels_england",
    "oktoberfest",
    "open_decisions",
)
OVERVIEW_KEY_MAP = {
    "fly in": "fly_in",
    "airline (transatlantic)": "airline",
    "airline (muc→man)": "airline_muc_man",
    "transport (germany)": "transport_germany",
    "hotels — germany": "hotels_germany",
    "hotels — england": "hotels_england",
    "oktoberfest": "oktoberfest",
    "key decisions open": "open_decisions",
}


def _all_bold(paragraph):
    runs = [r for r in paragraph.runs if r.text.strip()]
    return bool(runs) and all(r.bold for r in runs)


def _is_subheading(paragraph, text):
    if not _all_bold(paragraph):
        return False
    if len(text) > SUBHEADING_MAX:
        return False
    # A sub-heading is a label, not a sentence.
    return not text.endswith((".", "!", "?"))


def _split_names(value):
    """Split a Group Key traveler cell into individual names.

    ``"James, Regan, Debbie, John"`` and ``"Sara and Henry"`` both have to
    work, and "Sara and Henry" is two people, not one person by that name.
    """
    value = (value or "").strip().rstrip(".")
    if not value:
        return []
    # Drop a trailing count gloss like "— 4 people".
    value = re.split(r"\s*[–—-]\s*\d+\s+people?$", value)[0]
    return [p.strip() for p in NAME_SPLIT_RE.split(value) if p.strip()]


def _matches_weekday(weekday, iso_date):
    """Cross-check the day heading's own weekday against its date.

    Dates in the draft are ``2027-09-17`` strings, so the weekday has to come
    from the date object. A mismatch almost always means the year was inferred
    wrong, which would silently shift every date in the import.
    """
    if not iso_date or not weekday:
        return True
    try:
        return date.fromisoformat(iso_date).strftime("%a").lower() == weekday[:3].lower()
    except ValueError:
        return True


# --------------------------------------------------------------------------
# global tables
# --------------------------------------------------------------------------


def _collect_globals(document):
    """First pass over the tables the day walk refers back to.

    Same reasoning as the Taos parser: the Trip Overview, the Group Key and the
    booking list all sit away from the days that reference them, so they have
    to be collected before the walk rather than during it.
    """
    found = {"overview": {}, "group_key": [], "hotels": [], "hotel_ref": [], "bookings": []}
    for child in document.element.body.iterchildren():
        if child.tag.split("}")[-1] != "tbl":
            continue
        rows = _rows(child)
        if not rows:
            continue
        header = [c.strip().lower() for c in rows[0]]
        if header[:2] == ["detail", "info"]:
            for row in rows[1:]:
                if row and row[0].strip():
                    found["overview"][row[0].strip().lower()] = " | ".join(
                        c.strip() for c in row[1:] if c.strip()
                    )
        elif header[:3] == ["badge", "travelers", "leg"]:
            found["group_key"] = rows
        elif header[:3] == ["hotel", "location", "dates"]:
            found["hotels"] = rows[1:]
        elif header[:3] == ["hotel", "address", "phone"]:
            found["hotel_ref"] = rows[1:]
        elif header[:2] == ["priority", "item"]:
            found["bookings"] = rows[1:]
    return found


def _badge_rosters(group_key):
    """Map badge -> list of traveler names, as written in the Group Key."""
    rosters = {}
    for row in group_key[1:]:
        if not row or not row[0].strip():
            continue
        rosters[row[0].strip()] = _split_names(row[1] if len(row) > 1 else "")
    return rosters


def _resolve_badge(badge, rosters):
    """Resolve a day heading's badge to a roster.

    ``All 6 → splits`` is a day that starts as everybody and splits later, so
    it resolves against the "All 6" badge: every traveler is still on that
    day's plan, and the split is what the badge is telling you about.
    """
    cleaned = badge.strip()
    for arrow in ("→", "->"):
        if arrow in cleaned:
            cleaned = cleaned.split(arrow)[0].strip()
            break
    if cleaned in rosters:
        return cleaned, rosters[cleaned]
    for key, names in rosters.items():
        if key.lower() == cleaned.lower():
            return key, names
    for key, names in rosters.items():
        if key.lower() in cleaned.lower():
            return key, names
    return cleaned, []


# --------------------------------------------------------------------------
# trip-level records
# --------------------------------------------------------------------------


def _title_block(document, Paragraph):
    lines = []
    for child in document.element.body.iterchildren():
        if not child.tag.endswith("}p"):
            continue
        paragraph = Paragraph(child, document)
        if (paragraph.style.name or "").startswith("Heading"):
            break
        text = paragraph.text.strip()
        if text:
            lines.append(text)
    return lines


def _build_trip(parsed, lines, year_hint, overview, warn):
    headline = lines[0] if lines else "Europe"

    destinations = ""
    for line in lines[1:]:
        if "·" in line and "2027" not in line and "20" not in line[:4]:
            destinations = " · ".join(
                part.strip() for part in line.split("·") if part.strip()
            )
            break
    if not destinations:
        warn("Could not read the destination list from the title block")

    start = end = None
    for line in lines:
        match = re.search(
            r"([A-Za-z]+)\.?\s+(\d{1,2})\s*[–—-]\s*"
            r"(?:([A-Za-z]+)\.?\s+)?(\d{1,2}),?\s*(20\d{2})",
            line,
        )
        if match:
            mon1, d1, mon2, d2, year = match.groups()
            start = _to_date(mon1, d1, int(year))
            end = _to_date(mon2 or mon1, d2, int(year))
            break
    if start is None or end is None:
        warn("Could not read the trip date range from the title block")

    notes = [
        f"{key.replace('_', ' ').capitalize()}: {overview[src]}"
        for src, key in (
            ("fly in", "fly in"),
            ("airline (transatlantic)", "airline"),
            ("transport (germany)", "transport"),
            ("hotels — germany", "hotels"),
            ("hotels — england", "hotels"),
            ("oktoberfest", "oktoberfest"),
            ("key decisions open", "open decisions"),
        )
        if src in overview and overview[src]
    ]

    parsed.trip = {
        "name": f"{destinations} — {headline}" if destinations else headline,
        "destination": destinations,
        "start_date": start,
        "end_date": end,
        "notes": "\n\n".join(notes),
    }


def _build_travelers(parsed, overview, group_key, warn):
    """Travelers come from the Group Key, not the ``Travelers (Germany)`` row.

    The group key is a superset — it names Sara and Henry as their own badge
    even though the Germany row already lists them — so building from the key
    keeps one source of truth for both the traveler list and every roster.
    """
    order = []
    for row in group_key[1:]:
        for name in _split_names(row[1] if len(row) > 1 else ""):
            if name not in order:
                order.append(name)
    if not order:
        warn("No Group Key table found; falling back to the overview traveler list")
        order = _split_names(overview.get("travelers (germany)", ""))
    if not order:
        warn("No travelers could be read from this document")
    parsed.travelers = [{"name": name} for name in order]


def _build_lodging(parsed, hotels, year_hint, warn):
    """Concrete hotels become Lodging; a TBD one cannot.

    ``Lodging.check_in`` / ``check_out`` are required, and the Augsburg base is
    literally "TBD — Maximilian's or Airbnb" with no dates, so it cannot be a
    Lodging row. It is already item 3 on the Key Bookings list, so inventing a
    second task for it would just duplicate the real one; it is reported here
    instead.
    """
    for row in hotels:
        if not row:
            continue
        name = row[0].strip()
        if not name:
            continue
        dates = row[2].strip() if len(row) > 2 else ""
        nights = row[3].strip() if len(row) > 3 else ""
        features = row[4].strip() if len(row) > 4 else ""
        location = row[1].strip() if len(row) > 1 else ""

        if re.match(r"^tbd\b", name, re.IGNORECASE) or " or " in name.lower():
            warn(
                f"Hotel {name!r} is not booked yet, so it is not imported as "
                "Lodging (check_in/check_out are required). It is already on the "
                "Key Bookings list."
            )
            continue

        span = DATE_RANGE_RE.search(dates)
        if not span or not year_hint:
            warn(f"Could not read the stay dates for {name!r} from {dates!r}")
            continue
        check_in = _to_date(span.group("mon"), span.group("day"), year_hint)
        check_out = _to_date(
            span.group("mon2") or span.group("mon"), span.group("day2"), year_hint
        )
        if check_in is None or check_out is None:
            warn(f"Could not build dates for {name!r} from {dates!r}")
            continue

        parsed.lodging.append(
            {
                "name": name,
                "address": location,
                "check_in": check_in,
                "check_out": check_out,
                "nightly_rate": None,
                "currency": "EUR",
                "confirmation_number": "",
                "notes": "\n".join(filter(None, [features, f"{nights} nights" if nights else ""])),
            }
        )


def _build_contacts(parsed, hotel_ref, warn):
    """Hotel phones from the Quick Reference table become contacts."""
    for row in hotel_ref:
        if not row:
            continue
        name = row[0].strip()
        phone = row[2].strip() if len(row) > 2 else ""
        if not name or not phone or phone in ("—", "-"):
            continue
        address = row[1].strip() if len(row) > 1 else ""
        rooms = row[4].strip() if len(row) > 4 else ""
        parsed.contacts.append(
            {
                "name": f"{name} (front desk)",
                "role": "Hotel",
                "phone": phone,
                "email": "",
                "notes": "\n".join(filter(None, [address, rooms])),
            }
        )


def _build_booking_tasks(parsed, bookings, warn):
    """The Key Bookings table is the outstanding list, in priority order."""
    order = 0
    for row in bookings:
        if not row:
            continue
        title = row[1].strip() if len(row) > 1 else ""
        if not title:
            continue
        deadline = row[2].strip() if len(row) > 2 else ""
        notes = row[3].strip() if len(row) > 3 else ""

        priority = 3
        if row[0].strip():
            match = PRIORITY_RE.search(row[0])
            if match:
                priority = {
                    "critical": 1,
                    "high": 2,
                    "medium": 3,
                    "low": 4,
                }[match.group(1).lower()]
            else:
                warn(f"Unreadable priority {row[0]!r} for booking task {title!r}")

        order += 1
        parsed.booking_tasks.append(
            {
                "title": title[:200],
                "priority": priority,
                "due": None,
                "order": order,
                "notes": "\n".join(filter(None, [f"Deadline: {deadline}" if deadline else "", notes])),
            }
        )


# --------------------------------------------------------------------------
# the day walk
# --------------------------------------------------------------------------


def _start_day(parsed, text, match, year_hint, rosters, warn):
    mon, day_num, badge, rest = (
        match.group("mon"),
        match.group("day"),
        match.group("badge"),
        match.group("rest"),
    )
    weekday = text.split()[0]

    theme = rest.strip()
    hotel = ""
    hotel_match = HOTEL_IN_HEADING_RE.search(theme)
    if hotel_match:
        hotel = hotel_match.group(1).strip()
        theme = theme[: hotel_match.start()].strip()

    date_str = _to_date(mon, day_num, year_hint) if year_hint else None
    if date_str is None:
        warn(f"Could not read a date from the day heading {text!r}")
    elif not _matches_weekday(weekday, date_str):
        warn(
            f"Day heading says {weekday} but {date_str} is a "
            f"{date.fromisoformat(date_str):%A}; "
            "the year is probably wrong"
        )

    _key, names = _resolve_badge(badge, rosters)
    if not names:
        warn(f"Badge {badge!r} matched no Group Key row, so the day gets no roster")

    day = {
        "day_number": 0,
        "date": date_str,
        "theme": theme,
        "meals_included": False,
        "badge": badge,
        "roster": names,
        "hotel": hotel,
        "sections": [],
        "meals": [],
    }
    parsed.days.append(day)
    return day


def _current_phase(day):
    for section in reversed(day["sections"]):
        if section["section_type"] in ("phase", "choose_your_adventure"):
            return section
    return None


def _current_cya(day):
    for section in reversed(day["sections"]):
        if section["section_type"] == "choose_your_adventure":
            return section
    return None


def _add_option(day, letter, body, warn):
    cya = _current_cya(day)
    if cya is None:
        cya = _section(
            "choose_your_adventure",
            len(day["sections"]) + 1,
            title="Options",
            heading="Options",
            prompt="Pick one",
            summary="",
            options=[],
        )
        day["sections"].append(cya)
    title, sep, description = body.partition("—")
    # "OPTION A (recommended): Hampton Court Palace — train Windsor → ..."
    # The gloss is not part of the name, and only the first option in this
    # document is bold, so the caller matches on the OPTION marker rather than
    # on formatting.
    body = re.sub(r"^\([^)]*\)\s*[:\s]*", "", body).strip()
    title, sep, description = body.partition("—")
    cya["content"].setdefault("options", []).append(
        {
            "title": (title.strip().rstrip(":") or f"Option {letter}"),
            "letter": letter,
            "description": description.strip() if sep else body.strip(),
        }
    )


def _add_meals(day, rows, warn):
    """A ``Restaurant / Venue | Price | Why it fits`` table becomes meals."""
    for row in rows[1:]:
        if not row:
            continue
        name = row[0].strip()
        if not name or name in ("—", "-"):
            continue
        price = row[1].strip() if len(row) > 1 else ""
        why = row[2].strip() if len(row) > 2 else ""
        band = _price_band(price)
        day["meals"].append(
            {
                "name": name,
                "meal_type": _meal_type_from(name),
                "cuisine": "",
                "price_range": band,
                "why_recommended": why,
                # PriceRange is dollar-only, so a European "€€" becomes "$$"
                # and the original symbol is kept here rather than lost. This
                # is the same fallback the Taos parser uses for a € band.
                "reservation_notes": "" if price == band else price,
                "order": len(day["meals"]) + 1,
            }
        )


def _price_band(value):
    """The model takes ``$``/``$$``/``$$$``; the draft mixes in ``€`` and ``£``.

    Returns ``""`` rather than ``None`` for "no band": ``Meal.price_range`` is
    NOT NULL, so an explicit ``None`` is rejected by the database.
    """
    value = (value or "").strip()
    if not value or value in ("—", "-"):
        return ""
    count = 0
    for char in value:
        if char in "$€£":
            count += 1
        else:
            break
    if count:
        return "$" * min(count, 4)
    return ""


def _handle_paragraph(day, text, paragraph, warn):
    option = OPTION_LINE_RE.match(text)
    if option:
        _add_option(day, option.group(1), option.group(2), warn)
        return

    if _is_subheading(paragraph, text):
        day["sections"].append(
            _section(
                "phase",
                len(day["sections"]) + 1,
                title=text,
                heading=text,
                summary="",
                highlights=[],
            )
        )
        return

    current = _current_phase(day)
    if current is not None:
        if current["content"].get("summary"):
            current["content"].setdefault("highlights", []).append(text)
        else:
            current["content"]["summary"] = text
    else:
        day["sections"].append(
            _section("free_text", len(day["sections"]) + 1, paragraphs=[text])
        )


CALLOUT_TONES = {
    "tip": "info",
    "critical": "warning",
    "action": "warning",
    "warning": "warning",
    "note": "warning",
    "book ahead": "info",
    "book": "info",
}


def _callout_tone(label):
    """The callout tone for a tip-box label like "💡 Tip", or None if it is not one."""
    key = re.sub(r"[^\w\s]", "", label).strip().lower()
    return CALLOUT_TONES.get(key)


def _handle_table(day, rows, warn):
    header = [c.strip().lower() for c in rows[0]]
    first = header[0] if header else ""

    # "Food Scene — X" is a sub-heading; the table under it is the meals.
    if first.startswith(MEAL_HEADER) or first in ("restaurant / venue", "restaurant"):
        _add_meals(day, rows, warn)
        return

    # A tip box is a two-column table with an emoji label on every row, and
    # each row becomes its own callout. Most boxes are one row, but several
    # stack two tips ("📅 Book" over "💡 Tip"); matching only one-row boxes
    # read those as a table whose first tip was the column headings. All rows
    # must be tips, so a real two-column table is never half-converted.
    tones = [_callout_tone(row[0]) if len(row) == 2 else None for row in rows]
    if tones and all(tones):
        for row, tone in zip(rows, tones):
            day["sections"].append(
                _section(
                    "callout",
                    len(day["sections"]) + 1,
                    title=row[0].strip(),
                    tone=tone,
                    text=row[1].strip(),
                )
            )
        return

    day["sections"].append(
        _section(
            "logistics_table",
            len(day["sections"]) + 1,
            title=_current_title(day),
            icon="",
            columns=[c.strip() for c in rows[0]],
            rows=[list(r) for r in rows[1:]],
        )
    )


def _current_title(day):
    current = _current_phase(day)
    return current["title"] if current else ""


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def parse_europe(document):
    """Parse the Europe draft and return a :class:`ParsedTrip`."""
    from docx.text.paragraph import Paragraph

    parsed = ParsedTrip()
    warn = parsed.warnings.append

    globals_ = _collect_globals(document)
    year_hint = _year_hint(document, Paragraph)
    rosters = _badge_rosters(globals_["group_key"])
    children = list(document.element.body.iterchildren())

    lines = _title_block(document, Paragraph)
    _build_trip(parsed, lines, year_hint, globals_["overview"], warn)
    _build_travelers(parsed, globals_["overview"], globals_["group_key"], warn)
    _build_lodging(parsed, globals_["hotels"], year_hint, warn)
    _build_contacts(parsed, globals_["hotel_ref"], warn)
    _build_booking_tasks(parsed, globals_["bookings"], warn)

    # Where the days stop. The draft interleaves legs ("Germany Leg" then
    # "England Leg") with heading styles, so a heading cannot mark the end of
    # the day walk — "Germany Leg — All 6 Together" would cut the England days
    # off. Instead the last day heading does, and the walk runs up to the
    # first heading after it ("Quick Reference"). Bounding at the last day
    # heading itself would throw away the final day's own body.
    last_day = -1
    for index, child in enumerate(children):
        if child.tag.split("}")[-1] == "p":
            text = Paragraph(child, document).text.strip()
            if text and EU_DAY_RE.match(text):
                last_day = index
    boundary = len(children)
    for index in range(last_day + 1, len(children)):
        child = children[index]
        if child.tag.split("}")[-1] != "p":
            continue
        style = Paragraph(child, document).style.name or ""
        if style.startswith("Heading"):
            boundary = index
            break

    day = None
    for index, child in enumerate(children):
        if index >= boundary:
            break
        tag = child.tag.split("}")[-1]

        if tag == "p":
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue
            match = EU_DAY_RE.match(text)
            if match:
                day = _start_day(parsed, text, match, year_hint, rosters, warn)
                continue
            if day is not None:
                _handle_paragraph(day, text, paragraph, warn)

        elif tag == "tbl":
            if day is None:
                continue
            rows = _rows(child)
            if rows:
                _handle_table(day, rows, warn)

    for number, record in enumerate(parsed.days, start=1):
        record["day_number"] = number

    if not parsed.days:
        warn("No day headings matched the Europe format")

    return parsed


def _year_hint(document, Paragraph):
    """The title block's ``September 17 – October 3, 2027`` gives the year.

    The day headings carry no year at all, so this has to be read before the
    walk — the same reason the Taos parser does it.

    A line holding a *date range* is preferred over any other line with a
    four-digit year, because the document's own title ("EUROPE 2027") contains
    one too. Taking the first match would happen to work while the title and
    the dates agree, and then silently date the whole trip a year out the first
    time they do not — every day would shift with no error raised.
    """
    fallback = None
    for child in document.element.body.iterchildren():
        if not child.tag.endswith("}p"):
            continue
        text = Paragraph(child, document).text.strip()
        match = re.search(r"\b(20\d{2})\b", text)
        if not match:
            continue
        if MONTHS_RE.search(text):
            return int(match.group(1))
        if fallback is None:
            fallback = int(match.group(1))
    return fallback
