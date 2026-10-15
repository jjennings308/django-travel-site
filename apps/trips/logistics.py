"""Read the travel rows of a day's logistics table (``Section`` type ``logistics_table``).

Pure, like ``docx_import``: no Django, no database. Itineraries written by hand (and the
Europe draft, see ``docx_europe``) describe hops as table rows such as::

    Transport Leg              | Train                      | Time     | Notes
    Butzbach → Frankfurt Hbf   | RE30 / Mittelhessen-Express| ~45 min  | Frequent service...

``proposed_legs(columns, rows)`` turns each row naming an "A → B" hop into a dict a
review page can show and the user can correct before planned ``TransportLeg`` rows are
made from it. Nothing is guessed that the row doesn't say: no times, and the mode only
from words in the row. Each hop has a ``strength``: ``"arrow"`` when the row draws an
arrow, ``"possible"`` when it was found only by the word "to" or reads "Via A → B" (a
route description in a day's schedule, "Continue to Angel Fire"); review pages tick only
arrows. ``total_notes(columns, rows)`` gives the "Total…" rows' text that isn't a time.
``match_city(text, cities)`` finds a catalogue city named in a station or place
("Frankfurt Hbf" -> Frankfurt).
"""
import re

ARROW = re.compile(r"^\s*(?P<a>.+?)\s*(?:→|->|⟶|–>|—>|\bto\b)\s*(?P<b>.+?)\s*$", re.IGNORECASE)
DRAWN_ARROW = re.compile(r"→|->|⟶|–>|—>")
SKIP_ROW = re.compile(r"^\s*(total|sum|overall)\b", re.IGNORECASE)
OPERATOR_COLUMNS = ("train", "mode", "operator", "carrier", "airline", "service", "company")
TIME_COLUMNS = ("time", "duration", "journey time", "travel time")
# "Depart ABQ → SLC" is ABQ → SLC: a verb in front of the first place isn't part of it.
LEADING_VERB = re.compile(r"^(?:depart(?:s|ing)?(?:\s+from)?|leave|leaving|from|arrive(?:\s+at)?|"
                          r"continue(?:\s+on)?(?:\s+to)?|drive(?:\s+to)?|head(?:\s+to)?)\s+", re.IGNORECASE)
# The first rough time in prose: "~35 min", "~1 hr 15 min", "2.5 hrs".
ROUGH_TIME = re.compile(r"~?\s*\d+(?:[.,]\d+)?\s*(?:h|hrs?|hours?|m|mins?|minutes?)\b"
                        r"(?:\s*\d+\s*(?:m|mins?|minutes?)\b)?", re.IGNORECASE)

# (mode, words): first match wins, checked against the whole row.
MODE_WORDS = (
    ("plane", (r"\bflight\b", r"\bfly\b", r"\bairline", r"✈", r"\bair\b")),
    ("train", (r"\bICE\b", r"\bIC\b", r"\bRE\d*\b", r"\bRB\d*\b", r"bahn", r"\brail", r"\btrain", r"avanti",
               r"express", r"\bhbf\b", r"\bstation\b", r"railway", r"\beurostar")),
    ("rental_car", (r"\brental\b", r"\bhire car\b", r"\bcar hire\b", r"\brent(ed)? a car\b")),
    ("pov", (r"\bdrive\b", r"\bdriving\b", r"\bcar\b")),
    ("walking", (r"\bwalk", r"\bon foot\b")),
)


def _mode(text):
    for mode, words in MODE_WORDS:
        if any(re.search(w, text, re.IGNORECASE) for w in words):
            return mode
    return "other"


def _time_column(columns):
    return next((i for i, c in enumerate(columns) if c.lower() in TIME_COLUMNS), None)


def proposed_legs(columns, rows):
    """[{"row": i, "origin", "destination", "mode", "operator", "notes", "duration",
    "strength"}] for each travel row. ``duration`` is a ``timedelta`` or None: from a
    Time/Duration column when it reads as one (that cell then leaves the notes), else the
    first rough time in the row's other text."""
    columns = [str(c or "").strip() for c in (columns or [])]
    operator_col = next((i for i, c in enumerate(columns) if c.lower() in OPERATOR_COLUMNS), None)
    time_col = _time_column(columns)
    legs = []
    for i, row in enumerate(rows or []):
        cells = [str(c or "").strip() for c in row]
        if not cells or any(SKIP_ROW.match(c) for c in cells[:1]):
            continue
        hop_col, match = next(((j, ARROW.match(c)) for j, c in enumerate(cells) if ARROW.match(c)), (None, None))
        if match is None:
            continue
        operator = cells[operator_col] if operator_col is not None and operator_col < len(cells) and operator_col != hop_col else ""
        duration = None
        if time_col is not None and time_col < len(cells) and time_col != hop_col:
            duration = rough_duration(cells[time_col])
        skip = {hop_col, operator_col} | ({time_col} if duration else set())
        rest = [c for j, c in enumerate(cells) if j not in skip and c and c not in ("—", "-")]
        # Prose rows ("München Hbf, mid-morning (~10am). No early alarm.") end the place
        # at the first comma or full stop; the rest of the sentence goes to the notes.
        destination, *more = re.split(r",\s|\.\s", match.group("b").strip(), maxsplit=1)
        tail = more[0] if more else ""
        if tail.strip():
            rest.insert(0, tail.strip())
        notes = " · ".join(rest)
        if duration is None:
            found = ROUGH_TIME.search(notes)
            duration = rough_duration(found.group(0)) if found else None
        hop = cells[hop_col]
        strength = "arrow" if DRAWN_ARROW.search(hop) and not re.match(r"\s*via\b", hop, re.IGNORECASE) else "possible"
        legs.append({
            "row": i,
            "origin": LEADING_VERB.sub("", match.group("a").strip()),
            "destination": destination.strip(),
            "mode": _mode(" ".join(cells)),
            "operator": "" if operator in ("—", "-") else operator,
            "notes": notes,
            "duration": duration,
            "strength": strength,
        })
    return legs


def total_notes(columns, rows):
    """[{"row": i, "note": str}] for each "Total…" row: its text other than the label, the
    time and dashes ("Arrive Augsburg mid-afternoon comfortably"). The day's total is
    computed from its legs now, so converting a table drops these rows and keeps the note."""
    columns = [str(c or "").strip() for c in (columns or [])]
    time_col = _time_column(columns)
    totals = []
    for i, row in enumerate(rows or []):
        cells = [str(c or "").strip() for c in row]
        if not cells or not SKIP_ROW.match(cells[0]):
            continue
        keep = [c for j, c in enumerate(cells[1:], start=1)
                if c and c not in ("—", "-") and j != time_col and not ROUGH_TIME.fullmatch(c.strip())]
        totals.append({"row": i, "note": " · ".join(keep)})
    return totals


def match_city(text, cities):
    """The city (from ``cities``: objects with ``.name``) named in ``text``, longest name
    first so "New York" beats "York"; None if none is named."""
    words = text.lower()
    for city in sorted(cities, key=lambda c: len(c.name), reverse=True):
        if re.search(r"(?<!\w)" + re.escape(city.name.lower()) + r"(?!\w)", words):
            return city
    return None


_DURATION_PART = re.compile(r"(\d+(?:[.,]\d+)?)\s*(d|days?|h|hrs?|hours?|m|mins?|minutes?)\b", re.IGNORECASE)


def rough_duration(text):
    """A rough door-to-door time as a ``timedelta``, or None: "~45 min", "2.5 hrs",
    "~1 hr 15 min", "1:15" (h:mm), "90m". Approximate on purpose (``TransportLeg.est_duration``)."""
    from datetime import timedelta
    text = (text or "").strip().lstrip("~≈ ").strip()
    if not text:
        return None
    clock = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if clock:
        return timedelta(hours=int(clock.group(1)), minutes=int(clock.group(2)))
    total, found = 0.0, False
    for number, unit in _DURATION_PART.findall(text):
        value = float(number.replace(",", "."))
        unit = unit.lower()
        total += value * (1440 if unit.startswith("d") else 60 if unit.startswith("h") else 1)
        found = True
    if not found or total <= 0:
        return None
    return timedelta(minutes=round(total))
