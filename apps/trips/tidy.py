"""Content clean-up suggestions for a trip (docs/plans/trip-page-ux.md, U7).

Pure, like ``logistics.py``: no Django, no database. ``suggest(snapshot, dismissed=())`` takes a
plain snapshot of a trip (built by ``tidying.snapshot``) and returns ``Suggestion``s — facts that
were typed twice and now have a home elsewhere. **Suggestions only**: nothing here changes data;
``tidying.apply`` carries out the ones an editor ticked.

Snapshot shape (plain dicts and lists)::

    {"notes": str,
     "days": [{"id", "number", "date",
               "sections": [{"id", "type", "title", "summary", "highlights": [...],
                             "paragraphs": [...], "text", "columns": [...], "rows": [[...]]}],
               "legs": [{"id", "origin", "destination"}],
               "stays": [{"id", "name"}],              # checking in or out that day
               "meals": [{"id", "name", "notes", "type", "time"}],   # time "HH:MM" or None
               "activities": [{"id", "title"}],
               "catalogue": [{"kind": "poi" | "activity" | "event", "id", "name"}]}],  # linked that day
     "trip_legs": [...], "trip_stays": [...],
     "tasks": [{"id", "title", "item": {"kind", "id", "label"} | None}],
     "known_numbers": [str],                          # confirmation numbers (never phones)
     "contact_phones": [str]}                         # digits of contacts already recorded

Kinds (``Suggestion.kind``):

1. ``repeats_item`` — a narrative line on a day names that day's leg, stay, meal or activity.
2. ``callout_task`` — a "Book…" callout repeats an open task.
3. ``phone`` — a phone number typed into text; becomes a contact linked to the item.
4. ``notes_repeat`` / ``notes_options`` — trip notes repeating legs or stays; a numbered list of
   options that is really a decision.
5. ``table_activity`` — a logistics table describing an activity of that day.
6. ``day_slip`` — "Day 3" written in Day 4's text (flag only).
7. ``meal_phase`` — an empty phase that is only a time and a meal ("~7pm — Dinner") on a day with one
   such meal: give the meal that reservation time (it then shows in the day's timeline) and remove the
   phase. Review only (never applied by ``tidy_trip --apply``).
8. ``catalogue_note`` — a callout naming a place, activity or event that one of the day's items is linked
   to (catalogue-notes plan, N5): move it to the catalogue as a note on it (pending until staff approve
   it; staff's are published), so every trip going there gets it. Review only.

Confidence is ``high`` only for exact name matches of kinds 1–2; ``manage.py tidy_trip --apply``
applies those and nothing else.
"""
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

STOPWORDS = {"book", "booking", "booked", "reserve", "reservations", "advance", "ahead", "people", "group",
             "with", "from", "this", "that", "together", "your", "will", "have", "need", "before", "after",
             "into", "about", "only", "every", "when", "then", "than", "some", "more", "most", "very"}
BOOK_TITLE = re.compile(r"\b(book|booking|reserve|reservation|critical)\b", re.IGNORECASE)
ARROW = re.compile(r"→|->|⟶|\bto\b", re.IGNORECASE)
CHECK = re.compile(r"^\s*check[\s-]*(in|out)\b", re.IGNORECASE)
PHONE = re.compile(r"(?<![\w€$£.])(\+?\(?\d[\d \-/().]{5,}\d)(?![\w%])")
NUMBERED = re.compile(r"^\s*(?:\(?\d{1,2}[.)]|option\s+[a-z0-9]{1,2}[:.)])\s+(.+)$", re.IGNORECASE)
DAY_REF = re.compile(r"\bDay\s+(\d{1,2})\b")
DASH = re.compile(r"\s+[—–-]\s+")
LABEL = re.compile(r"^\s*[\w ]{1,20}:\s*")  # "Lunch: ", "Dinner: " in front of the item's name
LEADS_WITHIN = 20  # the match must start this close to the line's start to be the line's subject


@dataclass
class Suggestion:
    key: str
    kind: str
    day: int | None
    where: str
    before: str
    after: str
    confidence: str = "low"
    actions: list = field(default_factory=list)  # [(action, label)]; empty = flag only
    change: dict = field(default_factory=dict)

    @property
    def flag_only(self):
        return not self.actions


def _key(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _norm(text):
    return " ".join((text or "").lower().split())


def _first_word(text):
    words = re.findall(r"[\w'’]+", text or "")
    return words[0].lower() if words else ""


def _has_word(text, word):
    return bool(word) and re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text.lower()) is not None


def _words(text):
    """Significant words, crudely stemmed (a trailing "s" dropped)."""
    out = set()
    for word in re.findall(r"[a-zäöüß]{4,}", (text or "").lower()):
        word = word[:-1] if word.endswith("s") and len(word) > 4 else word
        if word not in STOPWORDS:
            out.add(word)
    return out


def _digits(text):
    return re.sub(r"\D", "", text or "")


def _extra_after(line, match_end):
    """Words after the matched part: what follows " — ", else the rest of the line."""
    parts = DASH.split(line, maxsplit=1)
    if len(parts) == 2:
        return parts[1].strip(" .;,")
    return line[match_end:].strip(" .;,—–-")


# ---- 1. a narrative line repeats one of the day's items --------------------------------------
def _narrative_lines(section):
    """(field, index, text) for every line of prose in a section."""
    if section["type"] == "phase":
        if section.get("summary"):
            yield "summary", None, section["summary"]
        for i, line in enumerate(section.get("highlights") or []):
            yield "highlights", i, line
    elif section["type"] == "free_text":
        for i, line in enumerate(section.get("paragraphs") or []):
            yield "paragraphs", i, line


def _leads(low, start):
    """Is a match at ``start`` the line's subject (near its start, after an optional label)?"""
    label = LABEL.match(low)
    offset = label.end() if label else 0
    return start - offset <= LEADS_WITHIN


def _match_item(line, day):
    """(kind, item, end, high) for the first of the day's items this line names, or None. High
    only when the line is *about* the item (it leads the line): a passing mention inside a longer
    sentence is low confidence, because removing that line would lose its other words."""
    low = line.lower()
    if CHECK.match(line):
        for stay in day["stays"]:
            name = stay["name"].strip().lower()
            if len(name) >= 4 and name in low:
                return "stay", stay, low.index(name) + len(name), True
    for leg in day["legs"]:
        a, b = _first_word(leg["origin"]), _first_word(leg["destination"])
        if a and b and a != b and _has_word(line, a) and _has_word(line, b) and low.index(a) < low.rindex(b):
            if ARROW.search(line):
                return "leg", leg, low.rindex(b) + len(b), _leads(low, low.index(a))
    for kind, items, attr in (("meal", day["meals"], "name"), ("activity", day["activities"], "title")):
        for item in items:
            name = item[attr].strip().lower()
            if len(name) >= 6 and re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", low):
                start = low.index(name)
                # The line is about it when the name is followed by a dash, bracket, comma, full
                # stop or the end — not "Borough Market → Tate Modern" (a route past it).
                follows = low[start + len(name):].lstrip()
                about = not follows or follows[0] in "—–-(,.:;"
                return kind, item, start + len(name), _leads(low, start) and about
    return None


def _repeats_item(day, section):
    for field_name, index, line in _narrative_lines(section):
        found = _match_item(line, day)
        if found is None:
            continue
        kind, item, end, high = found
        label = item.get("name") or item.get("title") or f"{item.get('origin')} → {item.get('destination')}"
        extra = _extra_after(line, end)
        actions = [("remove", "Remove the line")]
        if extra:
            actions.append(("remove_keep", f"Remove it; add “{extra}” to the {kind}'s notes"))
        yield Suggestion(
            key=_key("repeats_item", section["id"], field_name, index, line),
            kind="repeats_item", day=day["number"], where=section["title"] or "Plan",
            before=line, after=f"(shown by the {kind}: {label})", confidence="high" if high else "low",
            actions=actions,
            change={"op": "remove_line", "section": section["id"], "field": field_name, "index": index,
                    "line": line, "item": {"kind": kind, "id": item["id"]}, "extra": extra})


# ---- 2. a callout repeats an open task -------------------------------------------------------
def _callout_task(day, section, tasks):
    if section["type"] != "callout":
        return
    text = f"{section.get('title') or ''} {section.get('text') or ''}"
    words = _words(text)
    best, best_overlap = None, 1
    for task in tasks:
        overlap = len(words & _words(task["title"]))
        item = task.get("item")
        if item and item.get("label") and _words(item["label"]) <= words and _words(item["label"]):
            overlap += 1
        if overlap > best_overlap:
            best, best_overlap = task, overlap
    if best is None:
        return
    titled = bool(BOOK_TITLE.search(section.get("title") or ""))
    actions = [("delete", "Delete the callout (the task shows on its item)")]
    if best.get("item"):
        actions.append(("to_info", f"Keep it as an info note on {best['item']['label']}"))
    yield Suggestion(
        key=_key("callout_task", section["id"], best["id"], text),
        kind="callout_task", day=day["number"], where=section.get("title") or "Callout",
        before=(section.get("text") or "").strip(), after=f"(task: {best['title']})",
        confidence="high" if titled else "low", actions=actions,
        change={"op": "callout", "section": section["id"], "task": best["id"], "item": best.get("item"),
                "title": section.get("title") or "", "text": section.get("text") or ""})


# ---- 3. phone numbers typed into text --------------------------------------------------------
def _phones(text, known_digits):
    for match in PHONE.finditer(text or ""):
        number = match.group(1).strip()
        digits = _digits(number)
        if not 7 <= len(digits) <= 15 or digits in known_digits:
            continue
        if re.fullmatch(r"\d{4}\s*[–-]\s*\d{2,4}", number):  # a year range, not a phone
            continue
        yield number


def _without(text, number):
    after = text.replace(number, "")
    after = re.sub(r"\s{2,}", " ", after)
    return re.sub(r"\s+([,.;:])", r"\1", after).strip(" ,;:—–-")


def _name_before(line, number):
    before = line.split(number, 1)[0]
    before = re.sub(r"(call|phone|tel|telephone|mobile|ring)(\s+ahead)?\s*:?\s*$", "", before.strip(),
                    flags=re.IGNORECASE)
    words = before.strip(" :—–-·,(").split("—")[-1].strip()
    return words[-60:] or "Phone number"


# ---- 5. a table describes an activity --------------------------------------------------------
def _table_activity(day, section):
    if section["type"] != "logistics_table":
        return
    title = _norm(section.get("title"))
    for activity in day["activities"]:
        name = _norm(activity["title"])
        if len(name) >= 5 and title and (name in title or title in name):
            yield Suggestion(
                key=_key("table_activity", section["id"], activity["id"]),
                kind="table_activity", day=day["number"], where=section.get("title") or "Table",
                before=f"{len(section.get('rows') or [])} rows: " + "; ".join(
                    " | ".join(str(c) for c in row) for row in (section.get("rows") or [])[:2]),
                after=f"An info note on {activity['title']}, the table removed",
                actions=[("to_info", "Move the rows into an info note on the activity")],
                change={"op": "table_to_info", "section": section["id"], "activity": activity["id"],
                        "title": section.get("title") or activity["title"],
                        "columns": section.get("columns") or [], "rows": section.get("rows") or []})
            return


# ---- 7. an empty phase that is only "time — Dinner" --------------------------------------------
MEAL_WORDS = {"breakfast": "breakfast", "brunch": "breakfast", "lunch": "lunch", "dinner": "dinner",
              "supper": "dinner", "drinks": "drinks", "snack": "snack"}
CLOCK = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.IGNORECASE)


#: Without am/pm, an hour below this is read as the afternoon/evening for that meal ("7:30 dinner").
PM_BELOW = {"lunch": 6, "dinner": 12, "drinks": 12}


def clock_time(text, meal_type=""):
    """The first time in ``text`` as "HH:MM" ("~7pm" → 19:00, "~6:30–7pm" → 18:30, "19:00"), else None.
    In a range, a missing am/pm is taken from the end of the range ("6:30–7pm" is pm); with none at all,
    ``meal_type`` decides ("7:30 dinner" is 19:30, "1:00 lunch" is 13:00)."""
    times = list(CLOCK.finditer(text or ""))
    if not times:
        return None
    first = times[0]
    hour, minute = int(first.group(1)), int(first.group(2) or 0)
    meridiem = (first.group(3) or next((t.group(3) for t in times[1:] if t.group(3)), "") or "").lower()
    if not meridiem and not first.group(2) and hour <= 12:
        return None  # a bare number ("Day 7"), not a time
    if not meridiem and hour < PM_BELOW.get(meal_type, 0):
        meridiem = "pm"
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def _meal_phase(day, section):
    if section["type"] != "phase" or section.get("summary") or section.get("highlights"):
        return
    heading = section.get("heading") or section.get("title") or ""
    words = [w.lower() for w in re.findall(r"[A-Za-z]+", heading) if w.lower() not in ("am", "pm", "and")]
    if len(words) != 1 or words[0] not in MEAL_WORDS:
        return  # only "<time> — Dinner": a phase with more words is narrative, not a placeholder
    meals = [m for m in day["meals"] if m.get("type") == MEAL_WORDS[words[0]]]
    if len(meals) != 1:
        return
    meal, time = meals[0], clock_time(heading, MEAL_WORDS[words[0]])
    if meal.get("time"):
        after, actions = (f"(shown by the meal: {meal['name']} at {meal['time']})",
                          [("remove", "Remove the phase (the meal is in the timeline)")])
    elif time:
        after, actions = (f"{meal['name']} at {time}, in the day's timeline",
                          [("time_remove", f"Set {meal['name']} to {time} and remove the phase")])
    else:
        return
    yield Suggestion(
        key=_key("meal_phase", section["id"], meal["id"], heading),
        kind="meal_phase", day=day["number"], where=heading, before=heading, after=after,
        confidence="high", actions=actions,
        change={"op": "meal_phase", "section": section["id"], "heading": heading, "meal": meal["id"],
                "time": time})


# ---- 8. a callout about a place, activity or event linked that day ----------------------------
CALLOUT_TONES = {"info": "tip", "tip": "tip", "warning": "warning", "critical": "critical"}


def _fold(text):
    text = unicodedata.normalize("NFKD", (text or "").casefold())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def _catalogue_note(day, section):
    if section["type"] != "callout" or not (section.get("text") or "").strip():
        return
    said = _fold(f"{section.get('title') or ''} {section.get('text') or ''}")
    named = [t for t in day.get("catalogue", []) if len(_fold(t["name"])) >= 4
             and re.search(r"(?<!\w)" + re.escape(_fold(t["name"])) + r"(?!\w)", said)]
    if not named:
        return
    target = max(named, key=lambda t: len(t["name"]))  # "Marburg Castle Museum" over "Marburg Castle"
    title = re.sub(r"^[^\w]+", "", section.get("title") or "").strip()
    text = section["text"].strip()
    if title and _fold(title) not in _fold(text) and _fold(title) != _fold(target["name"]) \
            and not BOOK_TITLE.fullmatch(title):  # the title adds something ("Cash only: …")
        text = f"{title}: {text}"
    yield Suggestion(
        key=_key("catalogue_note", section["id"], target["kind"], target["id"], section["text"]),
        kind="catalogue_note", day=day["number"], where=section.get("title") or "Callout",
        before=section["text"].strip(),
        after=f"This looks like a note about {target['name']}: a catalogue note on it, shown on every trip "
              "that goes there (once staff approve it)",
        actions=[("to_catalogue", f"Move it to the catalogue as a note on {target['name']}")],
        change={"op": "to_catalogue", "section": section["id"], "target": target, "text": section["text"],
                "note": text, "tone": CALLOUT_TONES.get(section.get("tone") or "", "tip")})


# ---- 6. "Day N" written on another day -------------------------------------------------------
def _day_slips(day, section):
    texts = [line for _f, _i, line in _narrative_lines(section)]
    if section["type"] == "callout":
        texts.append(section.get("text") or "")
    for text in texts:
        for match in DAY_REF.finditer(text):
            number = int(match.group(1))
            if number != day["number"]:
                yield Suggestion(
                    key=_key("day_slip", section["id"], text),
                    kind="day_slip", day=day["number"], where=section.get("title") or "Text",
                    before=text, after=f"Says “Day {number}” on Day {day['number']} — check it by hand.")
                break


# ---- the whole trip --------------------------------------------------------------------------
def suggest(snapshot, dismissed=()):
    """Every suggestion for the trip, minus the dismissed keys, in day order (trip notes last)."""
    dismissed = set(dismissed)
    known = {_digits(n) for n in snapshot.get("known_numbers", []) if _digits(n)}
    known |= {_digits(p) for p in snapshot.get("contact_phones", []) if _digits(p)}
    out = []
    for day in snapshot["days"]:
        for section in day["sections"]:
            out += list(_repeats_item(day, section))
            out += list(_callout_task(day, section, snapshot.get("tasks", [])))
            out += list(_table_activity(day, section))
            out += list(_day_slips(day, section))
            out += list(_meal_phase(day, section))
            out += list(_catalogue_note(day, section))
            for field_name, index, line in list(_narrative_lines(section)) + (
                    [("text", None, section.get("text") or "")] if section["type"] == "callout" else []):
                for number in _phones(line, known):
                    named = _match_item(line, day)
                    if named and named[0] in ("meal", "activity"):
                        item = named[1]
                        name = item.get("name") or item.get("title")
                        link, on = {"kind": named[0], "id": item["id"]}, name
                    else:
                        name = section.get("title") or _name_before(line, number)
                        link, on = {"kind": "section", "id": section["id"]}, "this section"
                    out.append(Suggestion(
                        key=_key("phone", section["id"], field_name, index, number),
                        kind="phone", day=day["number"], where=section.get("title") or "Text",
                        before=line, after=_without(line, number),
                        actions=[("contact", f"Make “{number}” a contact on {on}")],
                        change={"op": "phone", "place": {"type": "section", "id": section["id"],
                                                         "field": field_name, "index": index},
                                "number": number, "name": name, "link": link}))
        for meal in day["meals"]:
            for number in _phones(meal.get("notes"), known):
                out.append(Suggestion(
                    key=_key("phone", "meal", meal["id"], number),
                    kind="phone", day=day["number"], where=meal["name"], before=meal["notes"],
                    after=_without(meal["notes"], number),
                    actions=[("contact", f"Make “{number}” a contact on {meal['name']}")],
                    change={"op": "phone", "place": {"type": "meal", "id": meal["id"]}, "number": number,
                            "name": meal["name"], "link": {"kind": "meal", "id": meal["id"]}}))
    out += list(_trip_notes(snapshot, known))
    return [s for s in out if s.key not in dismissed]


def _trip_notes(snapshot, known):
    lines = (snapshot.get("notes") or "").splitlines()
    stays = [s["name"].strip().lower() for s in snapshot.get("trip_stays", []) if len(s["name"].strip()) >= 4]
    legs = [(_first_word(leg["origin"]), _first_word(leg["destination"])) for leg in snapshot.get("trip_legs", [])]
    i = 0
    while i < len(lines):
        line = lines[i]
        if NUMBERED.match(line):
            j = i
            while j < len(lines) and NUMBERED.match(lines[j]):
                j += 1
            if j - i >= 2:
                block = lines[i:j]
                heading = next((lines[k].strip().rstrip(":") for k in range(i - 1, -1, -1) if lines[k].strip()), "")
                title = heading[:200] or "Decision from the trip notes"
                yield Suggestion(
                    key=_key("notes_options", "\n".join(block)), kind="notes_options", day=None,
                    where="Trip notes", before="\n".join(block), after=f"A decision “{title}” with {len(block)} options",
                    actions=[("decision", "Make it a decision task with these options")],
                    change={"op": "notes_options", "lines": block, "title": title,
                            "options": [NUMBERED.match(b).group(1).strip()[:200] for b in block]})
                i = j
                continue
        low = line.lower()
        if line.strip() and (any(name in low for name in stays) or any(
                a and b and a != b and _has_word(line, a) and _has_word(line, b) and ARROW.search(line)
                for a, b in legs)):
            yield Suggestion(
                key=_key("notes_repeat", line), kind="notes_repeat", day=None, where="Trip notes",
                before=line, after="(shown by the trip's legs and stays)",
                actions=[("remove", "Remove the line from the trip notes")],
                change={"op": "notes_remove", "line": line})
        for number in _phones(line, known):
            # A contact block in the notes ("Taxi Augsburg eG" / "Local taxi dispatch…" / "Phone: …"):
            # the block's first line names it, the lines between are its notes, and the block goes.
            start = i
            while start > 0 and lines[start - 1].strip() and not any(_phones(lines[start - 1], set())):
                start -= 1
            block = lines[start:i + 1]
            rest = _without(line, number)
            bare = re.fullmatch(r"(phone|tel|telephone|mobile|call)?\s*:?", rest.strip(), re.IGNORECASE)
            if bare and 2 <= len(block) <= 4:
                name, note_lines, remove = block[0].strip()[:200], [b.strip() for b in block[1:-1]], block
            else:
                name, note_lines = _name_before(line, number), []
                remove = [line] if bare else []
            yield Suggestion(
                key=_key("phone", "notes", number), kind="phone", day=None, where="Trip notes",
                before="\n".join(block if remove == block else [line]),
                after="(moved to a contact)" if remove else rest,
                actions=[("contact", f"Make “{name}” a contact ({number})")],
                change={"op": "phone", "place": {"type": "notes", "line": line, "rest": rest, "remove": remove},
                        "number": number, "name": name, "notes": "\n".join(note_lines), "link": None})
        i += 1
