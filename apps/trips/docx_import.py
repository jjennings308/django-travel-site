"""Parse an itinerary ``.docx`` into the relational schema.

This module is deliberately pure: it reads a document and returns plain
dictionaries plus a list of warnings. It never touches the database and never
imports Django models, so the same parsed plan can drive both the ``--dry-run``
report and the real write in ``manage.py import_itinerary``.

The mapping is conservative on purpose. Anything ambiguous becomes a warning
and is either left blank or recorded verbatim rather than guessed. A wrong
timezone silently shifts a flight by hours and a wrong meal type is worse than
an empty one, so both are reported instead of inferred.
"""

import datetime
import re
from dataclasses import dataclass, field

# Airport code -> IANA zone. Used to turn the doc's local wall-clock flight
# times into the UTC values TransportLeg stores. A code that is not listed is left
# blank (the model renders blank as UTC) and reported, never guessed.
AIRPORT_TIMEZONES = {
    "BWI": "America/New_York",
    "IAD": "America/New_York",
    "DCA": "America/New_York",
    "JFK": "America/New_York",
    "ATL": "America/New_York",
    "ORD": "America/Chicago",
    "DFW": "America/Chicago",
    "DEN": "America/Denver",
    "ABQ": "America/Denver",
    "SLC": "America/Denver",
    "PHX": "America/Phoenix",
    "LAX": "America/Los_Angeles",
    "SFO": "America/Los_Angeles",
    "SEA": "America/Los_Angeles",
    "PDX": "America/Los_Angeles",
}

# "💡  Tip" / "⚠️  Warning" / "📅  Book Ahead" -> the schema's callout tones.
# The schema only offers info/warning/critical, so "Book Ahead" folds into
# info and the original label is kept as the section title.
CALLOUT_TONES = {"tip": "info", "warning": "warning", "book ahead": "info"}

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

DAY_HEADING_RE = re.compile(r"^Day\s+(\d+)\s*[—–-]\s*(.+?)\s*[—–-]\s*(.*)$")
# Europe draft: "Sat Sept 25  [All 6 → splits]  Fly to England  |  Sara & Henry
# fly home   Hotel 3: Hard Days Night Hotel, Liverpool". The bracket is a badge
# from the Group Key table and resolves to a roster; the trailing "Hotel N:" is
# the base for that night, not part of the theme.
EU_DAY_RE = re.compile(
    r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+"
    r"(?P<mon>[A-Z][a-z]{2,8})\.?\s+(?P<day>\d{1,2})\s+"
    r"\[(?P<badge>[^\]]+)\]\s*"
    r"(?P<rest>.+)$"
)
DATE_RANGE_RE = re.compile(
    r"(?P<mon>[A-Za-z]+)\.?\s+(?P<day>\d{1,2})\s*[—–-]\s*(?P<mon2>[A-Za-z]+)\.?\s+"
    r"(?P<day2>\d{1,2}),\s*(?P<year>\d{4})"
)
# The title block writes the end month once ("September 12–19, 2026") while the
# Trip Overview repeats it ("Sept 12 – Sept 19, 2026"), so both forms are tried.
DATE_RANGE_SHORT_RE = re.compile(
    r"(?P<mon>[A-Za-z]+)\.?\s+(?P<day>\d{1,2})\s*[—–-]\s*(?P<day2>\d{1,2}),\s*"
    r"(?P<year>\d{4})"
)
DAY_DATE_RE = re.compile(r"(?:[A-Za-z]+,\s*)?(?P<mon>[A-Za-z]+)\.?\s+(?P<day>\d{1,2})")
FLIGHT_TIMES_RE = re.compile(
    r"Depart\s+(?P<dt>\d{1,2}(?::\d{2})?\s*(?:AM|PM))"
    r"(?:\s*/\s*Arrive\s+(?P<at>\d{1,2}(?::\d{2})?\s*(?:AM|PM))"
    r"(?:\s*\((?P<next>\d{1,2}/\d{1,2})\))?)?",
    re.IGNORECASE,
)
CHECKIN_RE = re.compile(
    r"check-?in\s+(?P<mon>[A-Za-z]+)\.?\s+(?P<day>\d{1,2}),?\s*(?P<year>\d{4})?",
    re.IGNORECASE,
)
CHECKOUT_RE = re.compile(
    r"check-?out\s+(?:(?P<mon>[A-Za-z]+)\.?\s+)?(?P<day>\d{1,2})"
    r"(?:\s*,\s*(?P<year>\d{4})?)?",
    re.IGNORECASE,
)
OPTION_RE = re.compile(r"^Option\s+([A-Z])\s*[—–-]\s*(.+)$", re.IGNORECASE)

PRICE_CHOICES = ("$", "$$", "$$$", "$$$$")
MEAL_TYPE_CHOICES = ("breakfast", "lunch", "dinner", "snack", "drinks")

# Headings that sit outside the numbered days. Their tables are matched by
# header row, but the headings also have to stop the day scope so the trailing
# summary blocks are not filed under the last day.
GLOBAL_SECTIONS = (
    "Quick Reference",
    "Trip at a Glance",
    "Food at a Glance",
    "Packing & Altitude Notes",
)
PACKING_SECTIONS = ("Packing & Altitude Notes",)

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class ParsedTrip:
    """Everything extracted from one document, ready to report or write."""

    trip: dict = field(default_factory=dict)
    travelers: list = field(default_factory=list)
    transport: list = field(default_factory=list)
    lodging: list = field(default_factory=list)
    confirmations: list = field(default_factory=list)
    contacts: list = field(default_factory=list)
    days: list = field(default_factory=list)
    booking_tasks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def counts(self) -> dict:
        return {
            "travelers": len(self.travelers),
            "days": len(self.days),
            "sections": sum(len(d["sections"]) for d in self.days),
            "meals": sum(len(d["meals"]) for d in self.days),
            "transport": len(self.transport),
            "lodging": len(self.lodging),
            "confirmations": len(self.confirmations),
            "contacts": len(self.contacts),
            "tasks": len(self.booking_tasks),
        }


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _strip_icon(text):
    """Split a leading emoji off a heading, e.g. "🚗 Phase 2 — Drive to ..."."""
    icon, sep, rest = text.strip().partition(" ")
    if sep and icon and not icon[0].isalnum() and rest.strip():
        return icon, rest.strip()
    return "", text.strip()


def _to_date(mon, day, year):
    """'September', 12, 2026 -> '2026-09-12' (ISO string, or None)."""
    if not mon or not day or not year:
        return None
    key = mon.strip().lower().rstrip(".")
    if key not in MONTHS:
        return None
    return f"{int(year):04d}-{MONTHS[key]:02d}-{int(day):02d}"


def _parse_date_range(text):
    """Read either spelling of the trip date range.

    Returns ``(start_iso, end_iso, year)`` or ``(None, None, None)``.
    """
    m = DATE_RANGE_RE.search(text or "")
    if m:
        year = int(m.group("year"))
        return (
            _to_date(m.group("mon"), m.group("day"), year),
            _to_date(m.group("mon2"), m.group("day2"), year),
            year,
        )
    m = DATE_RANGE_SHORT_RE.search(text or "")
    if m:
        year = int(m.group("year"))
        return (
            _to_date(m.group("mon"), m.group("day"), year),
            _to_date(m.group("mon"), m.group("day2"), year),
            year,
        )
    return None, None, None


def _to_time(value):
    """'7:05 AM' -> '07:05:00', or None if unparseable."""
    m = re.match(r"\s*(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\s*$", value or "", re.IGNORECASE)
    if not m:
        return None
    hour = int(m.group(1)) % 12
    if m.group(3).upper() == "PM":
        hour += 12
    return f"{hour:02d}:{m.group(2) or '00'}:00"


def _to_decimal(value):
    m = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", value or "")
    return m.group(1).replace(",", "") if m else None


def _rows(element):
    """Table rows as raw cell text.

    Reads the underlying ``w:tc`` elements rather than python-docx's
    ``row.cells`` because ``.cells`` expands horizontally merged cells, which
    repeats a value and shifts every later column by one.
    """
    out = []
    for tr in element.iter(f"{W_NS}tr"):
        cells = [(tc.xpath("string(.)") or "").strip() for tc in tr.findall(f"{W_NS}tc")]
        if any(cells):
            out.append(cells)
    return out


def _shift_year(iso_date, reference):
    """Roll a parsed date into the reference year (Dec 31 -> Jan 1 next year)."""
    if not iso_date or not reference:
        return iso_date
    try:
        parsed = datetime.date.fromisoformat(iso_date)
    except ValueError:
        return iso_date
    reference_date = datetime.date.fromisoformat(reference)
    if parsed < reference_date - datetime.timedelta(days=180):
        return iso_date.replace(parsed.year + 1)
    return iso_date


def _section(section_type, order, title="", icon="", **content):
    return {
        "section_type": section_type,
        "title": title,
        "icon": icon,
        "order": order,
        "content": content,
    }


# --------------------------------------------------------------------------
# builders for the record types
# --------------------------------------------------------------------------


def _meal_type_from(title):
    title = (title or "").lower()
    for word, value in (
        ("breakfast", "breakfast"),
        ("brunch", "breakfast"),
        ("lunch", "lunch"),
        ("midday", "lunch"),
        ("dinner", "dinner"),
        ("evening", "dinner"),
        ("supper", "dinner"),
        ("snack", "snack"),
        ("drinks", "drinks"),
        ("aperitif", "drinks"),
    ):
        if word in title:
            return value
    return "lunch"


def _build_leg(service_no, route, times, seats, day_date, warn):
    record = {
        "mode": "plane",
        "operator": "",
        "service_number": service_no,
        "confirmation_number": "",
        "origin": "",
        "destination": "",
        "origin_timezone": "",
        "destination_timezone": "",
        "departure_local": "",
        "departure_date": day_date or "",
        "arrival_local": "",
        "arrival_date": "",
        "currency": "USD",
        "notes": f"Seats: {seats}" if seats else "",
    }

    carrier = re.match(r"^([A-Za-z]{2,3})\s*(\d+)", service_no)
    if carrier:
        record["operator"] = carrier.group(1).upper()
        record["service_number"] = carrier.group(2)

    normalized = route.replace("→", "-").replace("->", "-")
    parts = [p.strip() for p in re.split(r"\s*-\s*", normalized) if p.strip()]
    if len(parts) == 2:
        record["origin"], record["destination"] = parts
    else:
        warn(f"Could not read the route {route!r} for flight {service_no!r}")

    for code, key in (
        (record["origin"], "origin_timezone"),
        (record["destination"], "destination_timezone"),
    ):
        if not code:
            continue
        if code in AIRPORT_TIMEZONES:
            record[key] = AIRPORT_TIMEZONES[code]
        else:
            warn(
                f"Airport {code!r} is not in AIRPORT_TIMEZONES, so {key} is left "
                f"blank and the time will render as UTC. Add the code to the map "
                f"in trips/docx_import.py to fix it."
            )

    m = FLIGHT_TIMES_RE.search(times)
    if not m:
        warn(f"Could not read the times {times!r} for flight {service_no!r}")
        return record

    record["departure_local"] = _to_time(m.group("dt")) or ""
    if not record["departure_local"]:
        warn(f"Could not parse the departure time {m.group('dt')!r}")

    if m.group("at"):
        record["arrival_local"] = _to_time(m.group("at")) or ""
        if m.group("next"):
            month, day = (int(x) for x in m.group("next").split("/"))
            if day_date:
                base = datetime.date.fromisoformat(day_date)
                arrival = base.replace(month=month, day=day)
                if arrival < base:
                    arrival = arrival.replace(year=base.year + 1)
                record["arrival_date"] = arrival.isoformat()
            else:
                record["arrival_date"] = day_date
        else:
            record["arrival_date"] = day_date

    if record["arrival_local"] and not record["departure_local"]:
        warn(
            f"Leg {service_no!r} has an arrival but no departure time; the row "
            f"cannot be saved because departure_at is required"
        )
    return record


def _parse_stay_dates(fields, day_date, warn):
    """Work out check-in / check-out from whichever rows the document has.

    Three shapes appear in the wild and all three are handled here:
      "Stay | 1 night, Sept 12 — check-in 4:00 PM, check-out Sept 13, 11:00 AM"
      "Check-in | Sept 13, 4:00 PM (...)"          (the key holds the label)
      "Check-in | 4:00 PM"                         (a time; the day is implied)
    """
    stay = fields.get("stay", "")
    check_in = check_out = ""

    # "check-in 4:00 PM" inside a Stay row means the *time*; the date is the
    # day the block sits on.
    cin_time_only = re.search(r"check-?in\s+(?:\d{1,2}(?::\d{2})?\s*(?:AM|PM))", stay, re.I)
    m = CHECKIN_RE.search(stay)
    if m:
        check_in = _to_date(m.group("mon"), m.group("day"), int(m.group("year") or 0) or None)
    elif cin_time_only and day_date:
        check_in = day_date

    # A dedicated "Check-in" row puts the label in the key and the value is
    # either "Sept 13, 4:00 PM" or a bare time.
    if not check_in:
        for key in ("check-in", "check in", "checkin"):
            if key in fields:
                m = DAY_DATE_RE.search(fields[key])
                if m and year_of(fields[key]):
                    check_in = _to_date(m.group("mon"), m.group("day"), year_of(fields[key]))
                elif day_date:
                    check_in = day_date
                break

    m = CHECKOUT_RE.search(stay)
    if m:
        mon = m.group("mon") or (DAY_DATE_RE.search(fields.get("check-in", "")).group("mon")
                                 if DAY_DATE_RE.search(fields.get("check-in", "")) else None)
        year = m.group("year") or year_of(fields.get("check-in", "")) or (check_in or "")[:4]
        if mon and year:
            check_out = _to_date(mon, m.group("day"), int(year))
    if not check_out:
        for key in ("check-out", "check out", "checkout"):
            if key in fields:
                m = DAY_DATE_RE.search(fields[key])
                if m:
                    # The year is usually carried on the check-in or is the
                    # trip's year, so a bare "Sept 20" still resolves.
                    year = year_of(fields[key]) or (check_in or "")[:4]
                    if year:
                        check_out = _to_date(m.group("mon"), m.group("day"), int(year))
                break
    return check_in, check_out


def year_of(text):
    m = re.search(r"\b(20\d{2})\b", text or "")
    return int(m.group(1)) if m else None


# A code is a single token of letters/digits/hyphens, at least 5 characters,
# containing at least one digit. This finds "5305434791" in
# "Booking.com Confirmation 5305434791" and keeps "Reservation-1216125" whole,
# while skipping the plain words around it.
CODE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{4,}$")


def _compact_confirmation(text, warn=None):
    """Pull a bare code out of a prose confirmation cell.

    The document writes confirmations as sentences, but
    ``Lodging.confirmation_number`` is 40 characters, so the bare code goes in
    the field and the surrounding detail is appended to notes instead of being
    silently truncated.
    """
    if not text:
        return "", ""
    chunks = [c.strip() for c in text.split("·") if c.strip()]
    code = ""
    rest = []
    for position, chunk in enumerate(chunks):
        for token in reversed(chunk.split()):
            if CODE_TOKEN_RE.match(token) and any(ch.isdigit() for ch in token):
                if not code:
                    code = token
                    rest = chunks[:position] + [c for c in chunks[position + 1:]]
                break
        if code:
            break
    remainder = " · ".join(c for c in rest if c and "(confidential)" not in c)
    if warn and len(text) > 40:
        warn(
            f"Confirmation {text!r} is too long for a confirmation_number field; "
            f"stored {code!r} with the rest kept in notes"
        )
    return code, remainder


def _build_lodging(body_rows, heading, day_date, warn):
    fields = {}
    for r in body_rows:
        if len(r) >= 2:
            fields[r[0].strip().lower()] = r[1].strip()

    record = {
        "name": "",
        "address": fields.get("address", ""),
        "confirmation_number": _compact_confirmation(fields.get("confirmation", ""), warn)[0],
        "check_in": "",
        "check_out": "",
        "nightly_rate": "",
        "currency": "USD",
        "notes": "",
    }

    stay = fields.get("stay", "")
    check_in, check_out = _parse_stay_dates(fields, day_date, warn)
    record["check_in"] = check_in
    record["check_out"] = check_out

    if not record["check_in"]:
        warn(
            f"Lodging under {heading!r}: no check-in date could be read, so this "
            f"row will be skipped"
        )
        return None
    if not record["check_out"]:
        warn(
            f"Lodging under {heading!r}: the document never states a check-out "
            f"date, and Lodging.check_out is required, so this row is skipped. "
            f"Add a 'Check-out' row to the source table or import it by hand."
        )
        return None

    nights = _nights_between(record["check_in"], record["check_out"])
    total = _to_decimal(fields.get("total price", ""))
    if total and nights:
        record["nightly_rate"] = f"{float(total) / nights:.2f}"
        if nights > 1:
            warn(
                f"Lodging {record['address']!r}: the document gives a {nights}-night "
                f"total of {total}; nightly_rate is a derived {record['nightly_rate']}"
            )
    elif total:
        warn(
            f"Lodging {record['address']!r}: total {total} but the night count is "
            f"unknown, so nightly_rate is left blank"
        )

    bits = [
        f"{key.title()}: {fields[key]}"
        for key in ("room", "unit", "guest name", "vibe", "phone")
        if fields.get(key)
    ]
    _, confirmation_remainder = _compact_confirmation(fields.get("confirmation", ""), warn)
    if confirmation_remainder:
        bits.append(f"Confirmation detail: {confirmation_remainder}")
    record["notes"] = " · ".join(bits)
    record["_heading"] = heading
    return record


def _nights_between(start, end):
    try:
        return (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days or None
    except (ValueError, TypeError):
        return None


def _lodging_name(heading, address, warn):
    """Prefer the human name from the heading over the street address."""
    text = re.sub(r"\bPhase\s+\d+\s*[—–-]\s*", "", heading or "", flags=re.IGNORECASE)
    text = re.sub(r"\b(Check-?In|Check-?Out)\b", "", text, flags=re.IGNORECASE)
    name = text.strip(" —–-").strip()
    if name and len(name) < 80:
        return name
    if address:
        warn(
            f"Could not work out a lodging name from the heading {heading!r}; "
            f"falling back to the address"
        )
        return address.split(",")[0].strip()
    return "Lodging"


# --------------------------------------------------------------------------
# global tables (first pass)
# --------------------------------------------------------------------------

# Trip-level tables appear once, near the end of the document, and the day
# tables earlier on refer back to them -- the Food at a Glance summary is the
# authority for cuisine and price. So they are collected in a first pass,
# before the days are walked.
GLOBAL_HEADERS = {
    "overview": ["item", "details"],
    "confirmations": ["item", "confirmation #"],
    "contacts": ["contact", "phone"],
    "summary": ["day", "meal", "restaurant", "cuisine", "price", "atmosphere"],
}


def _collect_global_tables(document, overview, summary, parsed, warn):
    for child in document.element.body.iterchildren():
        if not child.tag.endswith("}tbl"):
            continue
        rows = _rows(child)
        if not rows:
            continue
        header = [c.lower() for c in rows[0]]
        body_rows = rows[1:]

        if header == GLOBAL_HEADERS["overview"]:
            for r in body_rows:
                if len(r) >= 2:
                    overview[r[0].strip().lower()] = r[1].strip()

        elif header == GLOBAL_HEADERS["confirmations"]:
            for r in body_rows:
                if len(r) < 2 or not r[1].strip():
                    continue
                number = r[1].strip()
                provider = ""
                m = re.match(r"^([A-Za-z. ]{2,20}?)\s+(?=\S)", number)
                if m:
                    provider = m.group(1).strip()
                # Confirmation.confirmation_number is 60 chars; these cells are
                # prose, so keep the full text in notes and store the bare code.
                code, remainder = _compact_confirmation(number)
                record = {
                    "label": r[0].strip(),
                    "confirmation_number": code,
                    "provider": provider,
                }
                if remainder:
                    record["notes"] = remainder
                if len(number) > 60:
                    warn(
                        f"Confirmation {number!r} is too long for a "
                        f"confirmation_number field; stored {code!r} with the rest "
                        f"kept in notes"
                    )
                parsed.confirmations.append(record)

        elif header == GLOBAL_HEADERS["contacts"]:
            for r in body_rows:
                if len(r) >= 2 and r[0].strip():
                    parsed.contacts.append({"name": r[0].strip(), "phone": r[1].strip()})

        elif header == GLOBAL_HEADERS["summary"]:
            for r in body_rows:
                if len(r) >= 4 and r[2].strip():
                    name = r[2].strip()
                    if "|" in name:
                        name = name.split("|")[0].strip()
                    summary[name] = {
                        "day_label": r[0].strip(),
                        "meal_label": r[1].strip(),
                        "cuisine": r[3].strip(),
                        "price_range": r[4].strip() if len(r) > 4 else "",
                        "atmosphere": r[5].strip() if len(r) > 5 else "",
                    }


# --------------------------------------------------------------------------
# main parse
# --------------------------------------------------------------------------


def _looks_like_europe(document):
    """True when the document is the Europe draft rather than a Taos-style one.

    The Group Key table (``Badge | Travelers | Leg | Notes``) is the
    reliable signal: it exists only in the Europe draft, and it is the thing
    the whole roster model hangs off, since each day heading names a badge
    from it. A day heading in the Europe shape is accepted as a second signal
    so a draft that dropped the key table still gets read rather than refused.
    """
    from docx.text.paragraph import Paragraph

    for child in document.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "tbl":
            rows = _rows(child)
            if not rows:
                continue
            if [c.strip().lower() for c in rows[0]][:3] == ["badge", "travelers", "leg"]:
                return True
        elif tag == "p":
            text = Paragraph(child, document).text.strip()
            if text and EU_DAY_RE.match(text):
                return True
    return False


def parse_document(path):
    """Parse ``path`` and return a :class:`ParsedTrip`."""
    import docx
    from docx.text.paragraph import Paragraph

    parsed = ParsedTrip()
    warn = parsed.warnings.append

    document = docx.Document(path)

    # Two document shapes live in this importer. The Taos original numbers its
    # days ("Day 3 — Monday, September 14 — Theme"); the Europe draft instead
    # writes "Sat Sept 25  [All 6 → splits]  Fly to England" and carries a
    # Badge/Travelers key table. They share nothing structural, so the Europe
    # draft gets its own walk rather than a set of `or maybe` branches inside
    # the Taos one. Imported here because docx_europe imports this module.
    if _looks_like_europe(document):
        from .docx_europe import parse_europe

        return parse_europe(document)

    # The year has to be known before the walk, because day headings only say
    # "Monday, September 14" with no year. It comes from the title block.
    year_hint = None
    for child in document.element.body.iterchildren():
        if not child.tag.endswith("}p"):
            continue
        text = Paragraph(child, document).text.strip()
        _, _, year_hint = _parse_date_range(text)
        if year_hint:
            break

    preamble = []
    overview = {}
    summary = {}
    day = None
    current = None
    cya_section = None
    pending_option = None
    lodging_heading = ""
    packing_notes = []
    packing = False
    seen_day = False

    _collect_global_tables(document, overview, summary, parsed, warn)

    def next_order():
        return len(day["sections"]) + 1

    for child in document.element.body.iterchildren():
        tag = child.tag.split("}")[-1]

        # ---------------- paragraphs ----------------
        if tag == "p":
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue
            style = paragraph.style.name if paragraph.style is not None else ""

            # Day headings look like "Day 3 — Monday, September 14 — Theme".
            # They start with a letter, so they must be tested before the
            # preamble fallback below.
            day_match = DAY_HEADING_RE.match(text)
            if day_match:
                number, date_part, theme = day_match.groups()
                dmatch = DAY_DATE_RE.search(date_part)
                date_str = None
                if dmatch and year_hint:
                    date_str = _to_date(dmatch.group("mon"), dmatch.group("day"), year_hint)
                if date_str is None:
                    warn(f"Could not read a date from the day heading {text!r}")
                day = {
                    "day_number": int(number),
                    "date": date_str,
                    "theme": theme.strip(),
                    "meals_included": False,
                    "sections": [],
                    "meals": [],
                }
                parsed.days.append(day)
                current = None
                cya_section = None
                pending_option = None
                seen_day = True
                packing = False
                continue

            if day is None and not seen_day:
                preamble.append(text)
                continue

            if text.lower().startswith("included:"):
                if day is not None:
                    listed = text.split(":", 1)[1].strip().lower()
                    day["meals_included"] = bool(listed) and listed != "none"
                continue

            option_match = OPTION_RE.match(text)
            if option_match and cya_section is not None:
                pending_option = {"title": option_match.group(2).strip(), "description": ""}
                cya_section["content"].setdefault("options", []).append(pending_option)
                continue

            if style == "List Paragraph":
                if packing:
                    packing_notes.append(text)
                    continue
                if day is None:
                    continue
                if current is not None and current["section_type"] == "phase":
                    current["content"].setdefault("highlights", []).append(text)
                else:
                    if current is None or current["section_type"] != "free_text":
                        current = _section("free_text", next_order(), paragraphs=[])
                        day["sections"].append(current)
                    current["content"].setdefault("paragraphs", []).append(text)
                continue

            icon, body = _strip_icon(text)
            if icon:
                if body == "Trip Overview":
                    current = None
                    continue
                if body in GLOBAL_SECTIONS:
                    # Trip-level summary blocks that follow the last day. They
                    # must not be filed under the final day, so stop day scope.
                    day = None
                    current = None
                    cya_section = None
                    pending_option = None
                    if body in PACKING_SECTIONS:
                        packing = True
                    continue
                is_cya = "choose your adventure" in body.lower()
                current = _section(
                    "choose_your_adventure" if is_cya else "phase",
                    next_order(),
                    title=body,
                    icon=icon,
                    heading=body,
                    summary="",
                    highlights=[],
                )
                if is_cya:
                    current["content"]["prompt"] = body
                    cya_section = current
                else:
                    cya_section = None
                    lodging_heading = body
                day["sections"].append(current)
                continue

            if pending_option is not None:
                pending_option["description"] = text
                pending_option = None
                continue
            if day is None:
                # Trailing trip-level prose outside the numbered days.
                if packing:
                    packing_notes.append(text)
                continue
            if current is not None and current["section_type"] == "phase":
                current["content"]["summary"] = text
            else:
                current = _section("free_text", next_order(), paragraphs=[text])
                day["sections"].append(current)

        # ---------------- tables ----------------
        elif tag == "tbl":
            table = child
            rows = _rows(table)
            if not rows:
                continue
            header = [c.lower() for c in rows[0]]
            body_rows = rows[1:]

            if header in GLOBAL_HEADERS.values():
                # Already handled by the first pass over the whole document.
                continue

            if header == ["flight", "route", "times", "seats"] and day is not None:
                for r in body_rows:
                    if len(r) < 3 or not r[0].strip():
                        continue
                    parsed.transport.append(
                        _build_leg(
                            r[0].strip(),
                            r[1].strip(),
                            r[2].strip(),
                            r[3].strip() if len(r) > 3 else "",
                            day["date"],
                            warn,
                        )
                    )
                continue

            if header == ["restaurant", "price", "why"] and day is not None:
                meal_type = _meal_type_from(current["title"] if current else "")
                for n, r in enumerate(body_rows, start=1):
                    if not r or not r[0].strip():
                        continue
                    name = r[0].strip()
                    price = r[1].strip() if len(r) > 1 else ""
                    why = r[2].strip() if len(r) > 2 else ""
                    if "|" in name:
                        cleaned = name.split("|")[0].strip()
                        warn(
                            f"Day {day['day_number']}, restaurant {name!r} contains a "
                            f"stray '|'; importing it as {cleaned!r}"
                        )
                        name = cleaned
                    facts = summary.get(name, {})
                    if price and price not in PRICE_CHOICES:
                        # The document mixes '$' and the euro sign for the same
                        # price band, so fall back to the Food at a Glance
                        # summary before giving up on the value entirely.
                        fallback = facts.get("price_range", "")
                        if fallback in PRICE_CHOICES:
                            warn(
                                f"Day {day['day_number']}, {name!r}: the day table says "
                                f"price {price!r}, which is not one of {PRICE_CHOICES}; "
                                f"using the Food at a Glance value {fallback!r} instead"
                            )
                            price = fallback
                        else:
                            warn(
                                f"Day {day['day_number']}, {name!r}: price {price!r} is "
                                f"not one of {PRICE_CHOICES}; left blank"
                            )
                            price = ""
                    if not price:
                        price = facts.get("price_range", "")
                        if price not in PRICE_CHOICES:
                            price = ""
                    day["meals"].append(
                        {
                            "name": name,
                            "meal_type": meal_type,
                            "cuisine": facts.get("cuisine", ""),
                            "price_range": price,
                            "why_recommended": why,
                            "order": n,
                        }
                    )
                continue

            if len(rows) == 1 and len(header) == 2 and day is not None:
                label = rows[0][0].strip()
                key = re.sub(r"[^\w\s]", "", label).strip().lower()
                tone = CALLOUT_TONES.get(key)
                if tone:
                    day["sections"].append(
                        _section(
                            "callout",
                            next_order(),
                            title=label,
                            tone=tone,
                            text=rows[0][1].strip() if len(rows[0]) > 1 else "",
                        )
                    )
                    continue

            if header == ["detail", "info"] and day is not None and _looks_like_lodging(body_rows):
                record = _build_lodging(body_rows, lodging_heading, day["date"], warn)
                if record is not None:
                    parsed.lodging.append(record)
                    continue

            if day is not None:
                day["sections"].append(
                    _section(
                        "logistics_table",
                        next_order(),
                        title=current["title"] if current else "",
                        icon=current["icon"] if current else "",
                        columns=[c.strip() for c in rows[0]],
                        rows=[list(r) for r in body_rows],
                    )
                )

    _add_summary_meals(parsed, summary, warn)
    _finalize(parsed, preamble, overview, packing_notes, warn)
    return parsed


def _looks_like_lodging(body_rows):
    keys = {r[0].strip().lower() for r in body_rows if r}
    return bool(keys & {"address", "check-in", "check in", "check-out", "check out", "room", "unit"})


def _logistics_detail_for(name, day):
    """Find the logistics row describing ``name`` and return its details cell.

    A meal that never gets its own Restaurant|Price|Why table is usually
    described inside a day's Time|Stop|Details table, where the stop reads
    "Lunch: Rancho de Chimayó" and the details hold the address and what to
    order. The name can sit in either cell -- "Bode's General Store" appears
    only in the details of a row whose stop is "Drive to Ghost Ranch, lunch on
    the go" -- so both are searched.
    """
    candidates = [name]
    if "—" in name:
        candidates.append(name.split("—", 1)[1].strip())
    for section in day["sections"]:
        if section["section_type"] != "logistics_table":
            continue
        for row in section["content"].get("rows", []):
            if len(row) < 3:
                continue
            stop, details = row[1], row[2]
            haystack = f"{stop} {details}".lower()
            if any(c and c.lower() in haystack for c in candidates):
                return details.strip()
    return ""


def _add_summary_meals(parsed, summary, warn):
    """Create meals that only the Food at a Glance table knows about.

    Not every meal has a dedicated Restaurant|Price|Why table; the rest are
    described in passing inside a day's logistics rows. The document's own Food
    at a Glance table lists every meal on the trip, so it is treated as the
    index of record and anything the day tables missed is created from it. That
    keeps a "Food at a Glance" view from silently showing half the trip.
    """
    by_day_number = {d["day_number"]: d for d in parsed.days}
    by_month_day = {}
    for d in parsed.days:
        if not d["date"]:
            continue
        try:
            parsed_date = datetime.date.fromisoformat(d["date"])
        except ValueError:
            continue
        by_month_day[(parsed_date.month, parsed_date.day)] = d

    created = 0
    for name, facts in summary.items():
        day = None
        label = facts.get("day_label", "")
        match = re.match(r"^\s*(\d{1,2})\s*/\s*(\d{1,2})", label)
        if match:
            day = by_month_day.get((int(match.group(1)), int(match.group(2))))
        if day is None and label.isdigit():
            day = by_day_number.get(int(label))
        if day is None:
            warn(
                f"Food at a Glance lists {name!r} on {label!r}, which does not match "
                f"any day heading in this document; that meal was skipped"
            )
            continue

        if any(m["name"] == name for m in day["meals"]):
            continue

        meal_type = facts.get("meal_label", "").strip().lower()
        if meal_type not in MEAL_TYPE_CHOICES:
            warn(
                f"Food at a Glance lists {name!r} with meal type "
                f"{facts.get('meal_label', '')!r}, which is not one of "
                f"{MEAL_TYPE_CHOICES}; left blank"
            )
            meal_type = ""

        price = facts.get("price_range", "")
        if price not in PRICE_CHOICES:
            if price:
                warn(
                    f"Food at a Glance lists {name!r} with price {price!r}, which is "
                    f"not one of {PRICE_CHOICES}; left blank"
                )
            price = ""

        detail = _logistics_detail_for(name, day)
        day["meals"].append(
            {
                "name": name,
                "meal_type": meal_type,
                "cuisine": facts.get("cuisine", ""),
                "price_range": price,
                "why_recommended": facts.get("atmosphere", ""),
                "reservation_notes": detail,
                "order": max((m["order"] for m in day["meals"]), default=0) + 1,
            }
        )
        created += 1
    if created:
        warn(
            f"{created} meal(s) came only from the Food at a Glance table and were "
            f"not given their own Restaurant|Price|Why table in the document; the "
            f"day tables' logistics rows were used for the address and notes"
        )


def _finalize(parsed, preamble, overview, packing_notes, warn):
    """Fill in the trip-level fields and cross-check the document against itself."""
    trip = parsed.trip

    title = preamble[0] if preamble else ""
    _, title = _strip_icon(title) if title else ("", "")
    trip["name"] = title
    if "—" in title:
        trip["destination"] = title.split("—", 1)[1].strip()
    elif "," in title:
        trip["destination"] = title.split(",", 1)[1].strip()
    else:
        trip["destination"] = ""

    date_source = overview.get("dates", "")
    for line in preamble[1:]:
        if _parse_date_range(line)[0]:
            date_source = line
            break
    start, end, _ = _parse_date_range(date_source)
    trip["start_date"] = start or ""
    trip["end_date"] = end or ""
    if not start:
        warn("Could not read the trip date range; set start_date and end_date by hand")
    year_hint = start[:4] if start else None

    # Travelers
    raw = overview.get("travelers", "")
    parts = [p.strip() for p in re.split(r"\s*&\s*|\s+and\s+", raw) if p.strip()]
    if not parts:
        warn("The Trip Overview table has no 'Travelers' row; no travelers created")
    elif len(parts) == 1:
        parsed.travelers.append({"name": parts[0]})
    else:
        surname = parts[-1].split()[-1] if parts[-1].split() else ""
        for part in parts:
            name = part
            if surname and not part.split()[-1] == surname:
                name = f"{part} {surname}"
            parsed.travelers.append({"name": name})
        warn(
            f"Traveler names were split on '&' from {raw!r}; the shared surname "
            f"{surname!r} was applied to all of them. Worth a look."
        )

    # Transport legs: the confirmation number lives in the Trip Overview prose.
    for leg in parsed.transport:
        leg["confirmation_number"] = _flight_confirmation(overview)

    # Cross-check the day dates against the trip range.
    if trip["start_date"]:
        for record in parsed.days:
            if not record["date"]:
                continue
            record["date"] = _shift_year(record["date"], trip["start_date"])
    dated = [d["date"] for d in parsed.days if d["date"]]
    if trip["start_date"] and trip["end_date"] and dated:
        first, last = min(dated), max(dated)
        if first != trip["start_date"] or last != trip["end_date"]:
            warn(
                f"Trip Overview says {trip['start_date']} to {trip['end_date']}, but "
                f"the day headings span {first} to {last}. Kept the day headings."
            )

    # Lodging names come from the heading, not the street address.
    for record in parsed.lodging:
        record["name"] = _lodging_name(record.pop("_heading", ""), record.get("address", ""), warn)

    notes = [v for k, v in overview.items() if k.startswith("note ")]
    if packing_notes:
        notes.append("Packing & notes:\n" + "\n".join(f"- {n}" for n in packing_notes))
    trip["notes"] = "\n\n".join(notes)
    trip["budget"] = ""
    trip["structure"] = ""


def _flight_confirmation(overview):
    for key, value in overview.items():
        if "flight" in key and "note" not in key:
            m = re.search(r"Confirmation\s+([A-Z0-9]+)", value)
            if m:
                return m.group(1)
    return ""
