"""The old section types as day-first kinds, and decision to-dos as "choose one" groups.

**The retired types** (retire-old-section-types S2): phases, callouts, free text and "choose your adventure"
sections no longer exist on any trip — S1 converted them (``convert_day_first --all``) and the migration
that retired them converted any left. They still turn up in two places: Word documents (``docx_import`` /
``docx_europe`` parse into them) and old history snapshots (``changes.restore``). Both go through the
mappings here, which work on plain ``(section_type, title, content)`` so nothing needs a saved section:

* ``note_from`` — a phase, callout or free text as a **note** (``Section.Type.NOTE``, payload ``{"tone",
  "paragraphs"}``; the heading is the section's ``title``): a phase's heading, then its summary and each
  highlight as a "• " paragraph; a callout's title and text, its tone kept (info → tip); free text's title
  and paragraphs. Other payload keys are kept, so nothing an importer wrote is lost.
* ``adventure_group`` — a choose-your-adventure as a **"choose one" group**: prompt (else title), summary as
  notes, an option per option (description, then duration and cost, as its notes). ``import_itinerary``
  makes these.
* ``adventure_note`` — a choose-your-adventure as a note, for when a group won't do (a snapshot being
  restored onto its own row): the prompt as heading, summary, then "• title — description (duration ·
  cost)" per option.

The migration that retired the types (trips 0051) has its own frozen copy of ``note_from``; keep them in
step only for new code, never by importing this module from a migration.

**Decision to-dos** (a to-do with options, U6 — no longer made, retire-decision-todos D1) are converted on
review. Each goes to its own day, else its leg's, stay's or activity's day, else Day 1 (flagged "check the
day"). On its own day (never the Day 1 fallback) an open group whose prompt shares a significant word with
the to-do's title (``STOP_WORDS`` ignored, capitals and accents too), or that has an option titled like one
of its options, is a match: exactly one → the options are **merged** into it (``merge``: only titles it
lacks; a chosen one is picked while the group is open), more than one → asked on the page (the command
skips it); none → a **new group** (prompt = its title, each option's detail, link and cost; a chosen one
picked). The to-do stays open as a booking to-do (``kind`` book, options deleted, "Options moved to the
choice …" in its notes) unless it's ticked off instead. ``plan(trip, only)`` lists them by day without
saving; ``apply(trip, keys, targets, tick_off)`` converts in one transaction under one history line.
``trips:trip_convert`` (the review page, or one to-do's "Make it a choice") and ``manage.py
convert_day_first`` call them; ``pending_count`` is the trip page's banner number.
"""
from dataclasses import dataclass, field

from django.db import transaction

from .models import BookingTask

TONES = {"info": "tip", "tip": "tip", "warning": "warning", "critical": "critical"}
#: Section types retired in S2: never saved any more, still read from documents and old snapshots.
OLD_NOTE_TYPES = ("phase", "callout", "free_text")
ADVENTURE = "choose_your_adventure"
RETIRED = (*OLD_NOTE_TYPES, ADVENTURE)


def note_from(section_type, title, content):
    """A phase, callout or free text payload as a note: (title, content)."""
    content = dict(content) if isinstance(content, dict) else {}
    title = title or ""
    if section_type == "phase":
        title = (content.pop("heading", "") or title)[:200]
        paragraphs = [p for p in [content.pop("summary", "")] if p] + [f"• {h}" for h in content.pop("highlights", []) or []]
        tone = ""
    elif section_type == "callout":
        text = content.pop("text", "") or ""
        tone = TONES.get(content.pop("tone", "") or "info", "tip")
        paragraphs = [line for line in text.split("\n") if line.strip()]
    else:
        paragraphs = list(content.pop("paragraphs", []) or [])
        tone = ""
    content.update({"tone": tone, "paragraphs": paragraphs})
    return title, content


def _options(content):
    return [option for option in (content.get("options") or []) if isinstance(option, dict)]


def adventure_note(title, content):
    """A choose-your-adventure payload as a note: (title, content)."""
    content = dict(content) if isinstance(content, dict) else {}
    options = _options(content)
    content.pop("options", None)
    heading = (content.pop("prompt", "") or title or "Choose one")[:200]
    paragraphs = [p for p in [content.pop("summary", "") or ""] if p]
    for option in options:
        line = f"• {option.get('title') or 'Option'}"
        if option.get("description"):
            line += f" — {option['description']}"
        extra = " · ".join(str(option.get(k)) for k in ("duration", "cost") if option.get(k))
        if extra:
            line += f" ({extra})"
        paragraphs.append(line)
    content.update({"tone": "", "paragraphs": paragraphs})
    return heading, content


def adventure_group(title, content):
    """A choose-your-adventure payload as a group: {"prompt", "notes", "options": [{"title", "notes", …}]}."""
    content = content if isinstance(content, dict) else {}
    options = []
    for order, option in enumerate(_options(content)):
        extra = " · ".join(str(option.get(k)) for k in ("duration", "cost") if option.get(k))
        notes = "\n".join(p for p in (str(option.get("description") or ""), extra) if p)
        options.append({"title": (str(option.get("title") or "") or f"Option {order + 1}")[:200], "notes": notes,
                        "url": "", "est_cost": None, "currency": "", "order": order, "chosen": False})
    return {"prompt": (content.get("prompt") or title or "Choose one")[:200], "notes": content.get("summary") or "",
            "options": options}


def as_note(section_type, title, content):
    """Any retired type as a note: (title, content)."""
    if section_type == ADVENTURE:
        return adventure_note(title, content)
    return note_from(section_type, title, content)


def make_group(trip, day, prompt, notes, options, order=None):
    """An ``OptionGroup`` on ``day`` with its options (dicts as ``adventure_group`` makes); a chosen one is picked."""
    from .models import Option, OptionGroup
    group = OptionGroup.objects.create(trip=trip, day=day, prompt=prompt, notes=notes,
                                       order=day.option_groups.count() if order is None else order)
    chosen = None
    for data in options:
        option = Option.objects.create(group=group, title=data["title"], notes=data["notes"], url=data["url"] or "",
                                       est_cost=data["est_cost"], currency=data["currency"] or "", order=data["order"])
        if data["chosen"]:
            chosen = option
    if chosen is not None:
        group.pick(chosen)
    return group


@dataclass
class ChoiceConversion:
    """A decision to-do → a "choose one" group: merged into ``target`` (an open group on its day that looks
    like the same decision) or a new one on ``day``."""
    source: BookingTask
    day: object
    prompt: str
    notes: str
    options: list  # [{"title", "notes", "url", "est_cost", "currency", "order", "chosen"}]
    flag: str = ""  # something to check by hand ("no day: put on Day 1")
    blocked: str = ""  # why it can't be converted (left as it is)
    target: object = None  # the open group it merges into, else None (a new group)
    ambiguous: list = field(default_factory=list)  # more than one group looks like it: ask
    choices: list = field(default_factory=list)  # the day's open groups, for the page's select

    @property
    def key(self):
        return f"task-{self.source.pk}"

    @property
    def default_target(self):
        """The page's select value: ``group-<id>``, ``new``, or "" when it has to be asked."""
        if self.target is not None:
            return f"group-{self.target.pk}"
        return "" if self.ambiguous else "new"

    @property
    def skip(self):
        """Why the command leaves it (the page asks instead)."""
        if self.blocked:
            return self.blocked
        if self.ambiguous:
            return "looks like " + " and ".join(f"“{g.prompt}”" for g in self.ambiguous) + ": pick one on the page"
        return ""

    @property
    def before(self):
        return "Decision to-do", [self.source.title, *(f"• {o['title']}" + (" ✓" if o["chosen"] else "")
                                                        for o in self.options)]

    @property
    def after(self):
        if self.target is not None:
            have = _title_keys(o.title for o in self.target.options.all())
            return "Merge", [f"Merge into “{self.target.prompt}” (Day {self.day.day_number})",
                             *(f"• {o['title']}" + (" (already there)" if _keys(o["title"]) & have else "")
                               for o in self.options)]
        chosen = next((o["title"] for o in self.options if o["chosen"]), None)
        head = f"{self.prompt}" + (f" (picked: {chosen})" if chosen else " (undecided)")
        return "New choice", [head, *(f"• {o['title']}" + (f" — {o['notes']}" if o["notes"] else "")
                                      for o in self.options)]


#: Words too common in a decision's wording to say two are the same one (retire-decision-todos D1).
STOP_WORDS = {"which", "where", "what", "pick", "choose", "book", "the", "to", "in", "stay", "hotel", "a", "an",
              "and", "or", "of", "for", "on", "at", "our", "we", "do"}


def _keys(title):
    from .catalogue_links import match_keys
    return match_keys(title)


def _title_keys(titles):
    return {key for title in titles for key in _keys(title)}


def _words(text):
    """A title's significant words, each in all its match forms (capitals, accents, ö = oe)."""
    from .catalogue_links import normalise
    return {key for word in normalise(text).split() if word not in STOP_WORDS and len(word) > 1
            for key in _keys(word)}


def matching_groups(title, option_titles, groups):
    """Every group (``prompt`` and ``option_titles`` set) whose prompt shares a significant word with
    ``title``, or with an option titled like one of ``option_titles``. Pure."""
    words, options = _words(title), _title_keys(option_titles)
    return [g for g in groups
            if (words & _words(g.prompt)) or (options & _title_keys(getattr(g, "option_titles", ())))]


def match_group(title, option_titles, groups):
    """The one open group that looks like this decision, else None (none, or more than one: ask)."""
    found = matching_groups(title, option_titles, groups)
    return found[0] if len(found) == 1 else None


def _task_day(task, days):
    """(day, flag): its own day, else its item's, else Day 1 with a flag (only ever for a new group)."""
    if task.day_id:
        return next((d for d in days if d.pk == task.day_id), None), ""
    when = (task.leg.date if task.leg_id else task.stay.check_in if task.stay_id else
            task.activity.day.date if task.activity_id else None)
    found = next((d for d in days if when and d.date == when), None)
    if found is not None:
        return found, ""
    return (days[0] if days else None), "no day of its own: put on Day 1, check it"


def _from_task(task, days, groups=()):
    day, flag = _task_day(task, days)
    options = [{"title": o.title[:200], "notes": o.detail, "url": o.url, "est_cost": o.est_cost,
                "currency": o.currency, "order": o.order, "chosen": o.chosen} for o in task.options.all()]
    conversion = ChoiceConversion(task, day, task.title[:200], "", options, flag=flag,
                                  blocked="" if day is not None else "the trip has no days yet")
    if day is not None:
        conversion.choices = [g for g in groups if g.day_id == day.pk]
        if not flag:  # never match on the Day 1 fallback
            found = matching_groups(task.title, [o["title"] for o in options], conversion.choices)
            if len(found) == 1:
                conversion.target = found[0]
            elif found:
                conversion.ambiguous = found
    return conversion


def pending_count(trip):
    """Open to-dos with options still to turn into choices, from the trip page's prefetch (no query)."""
    return sum(1 for t in trip.booking_tasks.all() if not t.done and t.options.all())


def _decisions(trip):
    return list(trip.booking_tasks.filter(done=False, options__isnull=False).distinct()
                .select_related("leg", "stay", "activity__day").prefetch_related("options").order_by("pk"))


def _open_groups(trip):
    from .models import OptionGroup
    groups = list(trip.option_groups.filter(state=OptionGroup.State.OPEN).prefetch_related("options"))
    for group in groups:
        group.option_titles = [o.title for o in group.options.all()]
    return groups


def plan(trip, only=None):
    """[(day, [ChoiceConversion, …]), …] in day order, for every open to-do with options (or only the
    to-dos whose ids are in ``only``)."""
    days = list(trip.days.order_by("date", "day_number"))
    groups = _open_groups(trip)
    by_day = {day.pk: [] for day in days}
    for task in _decisions(trip):
        if only is not None and task.pk not in only:
            continue
        conversion = _from_task(task, days, groups)
        if conversion.day is not None:
            by_day[conversion.day.pk].append(conversion)
    return [(day, by_day[day.pk]) for day in days if by_day[day.pk]]


def merge(group, options, user=None):
    """Add the options ``group`` doesn't have yet (by title); a chosen one is picked while the group is
    open, else noted as "Earlier choice: …". Returns the items Pick made (a typed group, T2)."""
    from .models import Option
    existing = list(group.options.all())
    have = {key: option for option in existing for key in _keys(option.title)}
    order = max((o.order for o in existing), default=-1) + 1
    chosen = None
    for data in options:
        same = next((have[key] for key in _keys(data["title"]) if key in have), None)
        if same is None:
            same = Option.objects.create(group=group, title=data["title"], notes=data["notes"], url=data["url"] or "",
                                         est_cost=data["est_cost"], currency=data["currency"] or "", order=order)
            order += 1
            for key in _keys(same.title):
                have[key] = same
        if data["chosen"]:
            chosen = same
    if chosen is None:
        return []
    if group.state == group.State.OPEN:
        from .options import make_for
        group.pick(chosen, user)
        return make_for(group)
    group.notes = "\n".join(p for p in (group.notes, f"Earlier choice: {chosen.title}") if p)
    group.save(update_fields=["notes"])
    return []


def _resolve(conversion, choice):
    """The group to merge into (None = a new one), or False to leave it: ``choice`` is the page's select
    value, or None for the plan's own (an ambiguous one is left)."""
    if choice is None:
        return False if conversion.ambiguous else conversion.target
    if choice == "new":
        return None
    found = next((g for g in conversion.choices if f"group-{g.pk}" == choice), None)
    return found if found is not None else False


def apply(trip, keys=None, targets=None, tick_off=False, user=None):
    """Convert the chosen ones (every one when ``keys`` is None); returns how many. ``targets`` maps a key to
    the page's select value (``group-<id>`` / ``new``); ``tick_off`` is True or the keys whose to-do is
    ticked off instead of staying open as a booking to-do."""
    from .changes import batch
    wanted = None if keys is None else set(keys)
    targets = targets or {}
    count = 0
    with transaction.atomic(), batch("Converted decisions to choices", trip=trip):
        for _day, conversions in plan(trip):
            for conversion in conversions:
                if (wanted is not None and conversion.key not in wanted) or conversion.blocked:
                    continue
                group = _resolve(conversion, targets.get(conversion.key))
                if group is False:
                    continue
                if group is None:
                    group = make_group(trip, conversion.day, conversion.prompt, conversion.notes, conversion.options)
                else:
                    merge(group, conversion.options, user)
                task = conversion.source
                note = f"Options moved to the choice “{group.prompt}” on Day {conversion.day.day_number}."
                task.kind = BookingTask.Kind.BOOK
                task.done = tick_off is True or conversion.key in (tick_off or ())
                task.notes = "\n".join(p for p in (task.notes, note) if p)
                task.save(update_fields=["kind", "done", "notes"])
                task.options.all().delete()
                count += 1
    return count
