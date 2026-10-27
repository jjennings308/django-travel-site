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

**Decision to-dos** (``BookingTask.kind == "decide"`` with options, U6) are still converted on review:
each becomes a group on the task's day, else its leg's, stay's or activity's day, else Day 1 (flagged
"check the day"); prompt = its title; each option's detail, link and cost carried over; a chosen option is
kept as picked; the to-do is ticked off with a note saying where its choice went. ``plan(trip)`` lists
them by day without saving; ``apply(trip, keys)`` converts the chosen ones (``"task-<id>"``) in one
transaction under one history line. ``trips:trip_convert`` (the review page) and ``manage.py
convert_day_first`` call them; ``pending_count`` is the trip page's banner number.
"""
from dataclasses import dataclass

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
    """A decision to-do → a "choose one" group."""
    source: BookingTask
    day: object
    prompt: str
    notes: str
    options: list  # [{"title", "notes", "url", "est_cost", "currency", "order", "chosen"}]
    flag: str = ""  # something to check by hand ("no day: put on Day 1")
    blocked: str = ""  # why it can't be converted (left as it is)

    @property
    def key(self):
        return f"task-{self.source.pk}"

    @property
    def before(self):
        return "Decision to-do", [self.source.title, *(f"• {o['title']}" + (" ✓" if o["chosen"] else "")
                                                        for o in self.options)]

    @property
    def after(self):
        chosen = next((o["title"] for o in self.options if o["chosen"]), None)
        head = f"{self.prompt}" + (f" (picked: {chosen})" if chosen else " (undecided)")
        return "Choose one", [head, *(f"• {o['title']}" + (f" — {o['notes']}" if o["notes"] else "")
                                      for o in self.options)]


def _task_day(task, days):
    if task.day_id:
        return next((d for d in days if d.pk == task.day_id), None), ""
    when = (task.leg.date if task.leg_id else task.stay.check_in if task.stay_id else
            task.activity.day.date if task.activity_id else None)
    found = next((d for d in days if when and d.date == when), None)
    if found is not None:
        return found, ""
    return (days[0] if days else None), "no day of its own: put on Day 1, check it"


def _from_task(task, days):
    day, flag = _task_day(task, days)
    options = [{"title": o.title[:200], "notes": o.detail, "url": o.url, "est_cost": o.est_cost,
                "currency": o.currency, "order": o.order, "chosen": o.chosen} for o in task.options.all()]
    return ChoiceConversion(task, day, task.title[:200], "", options, flag=flag,
                            blocked="" if day is not None else "the trip has no days yet")


def pending_count(trip):
    """Open decision to-dos with options, from the trip page's prefetch (no query)."""
    return sum(1 for t in trip.booking_tasks.all() if t.kind == BookingTask.Kind.DECIDE and not t.done and t.options.all())


def _decisions(trip):
    return list(trip.booking_tasks.filter(kind=BookingTask.Kind.DECIDE, done=False)
                .select_related("leg", "stay", "activity__day").prefetch_related("options"))


def plan(trip):
    """[(day, [ChoiceConversion, …]), …] in day order, for every open decision to-do with options."""
    days = list(trip.days.order_by("date", "day_number"))
    by_day = {day.pk: [] for day in days}
    for task in _decisions(trip):
        if task.options.all():
            conversion = _from_task(task, days)
            if conversion.day is not None:
                by_day[conversion.day.pk].append(conversion)
    return [(day, by_day[day.pk]) for day in days if by_day[day.pk]]


def apply(trip, keys=None):
    """Convert the chosen ones (every one when ``keys`` is None); returns how many."""
    from .changes import batch
    wanted = None if keys is None else set(keys)
    count = 0
    with transaction.atomic(), batch("Converted decisions to choices", trip=trip):
        for _day, conversions in plan(trip):
            for conversion in conversions:
                if (wanted is not None and conversion.key not in wanted) or conversion.blocked:
                    continue
                group = make_group(trip, conversion.day, conversion.prompt, conversion.notes, conversion.options)
                task = conversion.source
                note = f"Moved to the choice “{group.prompt}” on Day {conversion.day.day_number}."
                task.done = True
                task.notes = "\n".join(p for p in (task.notes, note) if p)
                task.save(update_fields=["done", "notes"])
                count += 1
    return count
