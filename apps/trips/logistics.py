"""Read the travel rows of a day's logistics table (``Section`` type ``logistics_table``).

Pure, like ``docx_import``: no Django, no database. Itineraries written by hand (and the
Europe draft, see ``docx_europe``) describe hops as table rows such as::

    Transport Leg              | Train                      | Time     | Notes
    Butzbach → Frankfurt Hbf   | RE30 / Mittelhessen-Express| ~45 min  | Frequent service...

``proposed_legs(columns, rows)`` turns each row naming an "A → B" hop into a dict a
review page can show and the user can correct before planned ``TransportLeg`` rows are
made from it. Nothing is guessed that the row doesn't say: no times, and the mode only
from words in the row. ``match_city(text, cities)`` finds a catalogue city named in a
station or place ("Frankfurt Hbf" -> Frankfurt).
"""
import re

ARROW = re.compile(r"^\s*(?P<a>.+?)\s*(?:→|->|⟶|–>|—>|\bto\b)\s*(?P<b>.+?)\s*$", re.IGNORECASE)
SKIP_ROW = re.compile(r"^\s*(total|sum|overall)\b", re.IGNORECASE)
OPERATOR_COLUMNS = ("train", "mode", "operator", "carrier", "airline", "service", "company")

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


def proposed_legs(columns, rows):
    """[{"row": i, "origin", "destination", "mode", "operator", "notes"}] for each travel row."""
    columns = [str(c or "").strip() for c in (columns or [])]
    operator_col = next((i for i, c in enumerate(columns) if c.lower() in OPERATOR_COLUMNS), None)
    legs = []
    for i, row in enumerate(rows or []):
        cells = [str(c or "").strip() for c in row]
        if not cells or any(SKIP_ROW.match(c) for c in cells[:1]):
            continue
        hop_col, match = next(((j, ARROW.match(c)) for j, c in enumerate(cells) if ARROW.match(c)), (None, None))
        if match is None:
            continue
        operator = cells[operator_col] if operator_col is not None and operator_col < len(cells) and operator_col != hop_col else ""
        rest = [c for j, c in enumerate(cells) if j not in (hop_col, operator_col) and c and c not in ("—", "-")]
        # Prose rows ("München Hbf, mid-morning (~10am). No early alarm.") end the place
        # at the first comma or full stop; the rest of the sentence goes to the notes.
        destination, *more = re.split(r",\s|\.\s", match.group("b").strip(), maxsplit=1)
        tail = more[0] if more else ""
        if tail.strip():
            rest.insert(0, tail.strip())
        legs.append({
            "row": i,
            "origin": match.group("a").strip(),
            "destination": destination.strip(),
            "mode": _mode(" ".join(cells)),
            "operator": "" if operator in ("—", "-") else operator,
            "notes": " · ".join(rest),
        })
    return legs


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
