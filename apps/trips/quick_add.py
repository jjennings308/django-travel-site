"""One line typed into a day's **+ Add** (day-first plan, P3), read as a rough item.

Pure, like ``logistics`` (whose arrow, mode and rough-time parsing it reuses): no Django, no database.
``parse(text, kind=None)`` returns a dict with ``kind`` (``travel`` / ``stay`` / ``do`` / ``eat`` /
``note``) and that kind's fields; the view (``views.quick_add``) makes the item on its day. The kind is
guessed from the first word and the shape of the line unless a kind button forces it:

* **eat** — starts with a meal word: "Dinner Augustiner 7:30pm" → dinner at Augustiner, 19:30.
* **stay** — starts with hotel / stay / inn / … or says "N nights": "Hotel Laimer Hof 3 nights".
* **travel** — draws an arrow, or starts with a way of travelling and says "to": "Train Munich → Salzburg
  9:15" → a train, Munich to Salzburg, leaving around 9:15 (times stay rough: a planned leg has a day,
  not a booked time, so the time goes in its notes).
* **do** — starts with tour / tickets / museum / …, or has a time: "Tour of the salt mine 10am".
* **note** — anything else: the line becomes the note's text.

Nothing is guessed that the line doesn't say.
"""
import re
from datetime import time

from .logistics import ARROW, DRAWN_ARROW, LEADING_VERB, ROUGH_TIME, _mode, rough_duration

KINDS = ("travel", "stay", "do", "eat", "note")

MEAL_WORDS = {"breakfast": "breakfast", "brunch": "breakfast", "lunch": "lunch", "dinner": "dinner",
              "supper": "dinner", "snack": "snack", "coffee": "snack", "drinks": "drinks",
              "cocktails": "drinks"}
STAY_WORDS = ("hotel", "stay", "hostel", "inn", "apartment", "flat", "airbnb", "b&b", "bnb", "campsite",
              "camping", "guesthouse", "lodge", "motel", "resort", "villa", "cabin", "chalet")
TRAVEL_WORDS = ("train", "flight", "fly", "plane", "bus", "coach", "drive", "car", "ferry", "boat", "walk",
                "taxi", "uber", "tram", "metro", "subway", "rental", "transfer", "shuttle")
# (activity kind, first words)
DO_WORDS = (("tour", ("tour", "walking", "guided", "excursion", "cruise", "hike", "trip")),
            ("ticket", ("tickets", "ticket", "pass", "concert", "show", "game", "match", "opera", "theatre",
                        "theater")),
            ("entry", ("museum", "entry", "visit", "gallery", "castle", "palace", "cathedral", "tower", "exhibition")),
            ("table", ("table", "reservation")),
            ("car_hire", ("car hire", "hire car", "rent a car")))

NIGHTS = re.compile(r"\b(\d{1,2})\s*nights?\b", re.IGNORECASE)
CLOCK = re.compile(
    r"(?:\s*(?:\bat\b|@)\s*)?"
    r"(?<![\d:.])(?:(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*(?P<ap>[ap])\.?m\.?\b"  # 7pm, 7:30 pm, 7.30am
    r"|(?P<h24>\d{1,2})[:h](?P<m24>\d{2})\b)",  # 19:30, 9:15, 9h15
    re.IGNORECASE)


def find_time(text):
    """(time or None, the text without it)."""
    for match in CLOCK.finditer(text):
        if match.group("h"):
            hour, minute = int(match.group("h")), int(match.group("m") or 0)
            if not 1 <= hour <= 12:
                continue
            hour = hour % 12 + (12 if match.group("ap").lower() == "p" else 0)
        else:
            hour, minute = int(match.group("h24")), int(match.group("m24"))
        if hour > 23 or minute > 59:
            continue
        rest = (text[:match.start()] + " " + text[match.end():]).strip()
        return time(hour, minute), _tidy(rest)
    return None, text


def _tidy(text):
    return re.sub(r"\s{2,}", " ", text).strip(" ,;-—–")


def _first_word(text):
    match = re.match(r"\s*([\w&']+)", text.lower())
    return match.group(1) if match else ""


def _drop_first(text, words):
    """``text`` without a leading word from ``words`` (and an "at" / "of" after it)."""
    pattern = r"^\s*(?:" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + r")\b\s*(?:at|of|in|:)?\s*"
    return _tidy(re.sub(pattern, "", text, count=1, flags=re.IGNORECASE))


def _guess(text, has_time):
    first = _first_word(text)
    low = text.lower()
    if first in MEAL_WORDS:
        return "eat"
    if first in STAY_WORDS or NIGHTS.search(text):
        return "stay"
    if DRAWN_ARROW.search(text) or (first in TRAVEL_WORDS and re.search(r"\bto\b", low)):
        return "travel"
    if any(low.startswith(w) for _, words in DO_WORDS for w in words) or has_time:
        return "do"
    return "note"


def parse(text, kind=None):
    """The line as a rough item (see the module docstring). ``kind`` forces one of ``KINDS``."""
    text = _tidy(" ".join((text or "").split()))
    clock, without_time = find_time(text)
    kind = kind if kind in KINDS else _guess(text, clock is not None)
    if kind == "eat":
        first = _first_word(without_time)
        if first in MEAL_WORDS:
            name, meal_type = _drop_first(without_time, MEAL_WORDS), MEAL_WORDS[first]
        else:
            name, meal_type = without_time, _meal_type_for(clock)
        return {"kind": "eat", "name": name or without_time or "A meal", "meal_type": meal_type, "time": clock}
    if kind == "stay":
        nights = NIGHTS.search(without_time)
        name = _tidy(NIGHTS.sub("", without_time))
        if _first_word(name) == "stay":
            name = _drop_first(name, ("stay",))
        return {"kind": "stay", "name": name or "A stay", "nights": max(1, int(nights.group(1))) if nights else 1}
    if kind == "travel":
        duration_text = ROUGH_TIME.search(without_time)
        duration = rough_duration(duration_text.group(0)) if duration_text else None
        route = ROUGH_TIME.sub("", without_time) if duration_text else without_time
        mode = _mode(text)
        if mode == "other" and _first_word(text) in ("drive", "car"):
            mode = "pov"
        route = _drop_first(route, TRAVEL_WORDS) if _first_word(route) in TRAVEL_WORDS else route
        match = ARROW.match(route)
        if re.match(r"to\b", route, re.IGNORECASE):  # "Train to Salzburg": from wherever the day starts
            origin, destination = "", route[2:]
        elif match:
            origin, destination = LEADING_VERB.sub("", match.group("a")).strip(), match.group("b").strip()
        else:
            origin, destination = route, ""
        notes = f"Around {clock.strftime('%H:%M')}" if clock else ""
        return {"kind": "travel", "mode": mode, "origin": _tidy(origin), "destination": _tidy(destination),
                "duration": duration, "notes": notes}
    if kind == "do":
        low = without_time.lower()
        activity_kind = next((k for k, words in DO_WORDS if any(low.startswith(w) for w in words)), "other")
        return {"kind": "do", "title": without_time or "An activity", "activity_kind": activity_kind, "time": clock}
    return {"kind": "note", "text": text}


def _meal_type_for(clock):
    """A meal forced by the Eat button with no meal word: its type from the time, else dinner."""
    if clock is None:
        return "dinner"
    return "breakfast" if clock.hour < 11 else "lunch" if clock.hour < 16 else "dinner"
