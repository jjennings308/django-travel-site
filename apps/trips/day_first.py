"""Converting a trip's old content to the day-first kinds (day-first plan, decision 6), on review.

P3: phases, callouts and free text become **notes** (``Section.Type.NOTE``, payload ``{"tone",
"paragraphs"}``; the heading is the section's ``title``):

* a phase: heading (its ``heading``, else its title), then its summary as a paragraph and each highlight
  as a "• " paragraph;
* a callout: its title and text, its tone kept (info → tip);
* free text: its title and paragraphs.

Other keys in the payload are kept, as the payload forms keep them, so nothing an importer wrote is lost.

P4: "Choose your adventure" sections and decision to-dos become **"choose one" groups**
(``OptionGroup`` with an ``Option`` each):

* a choose-your-adventure section: on its day, prompt = its prompt (else title), its summary as the
  group's notes, an option per option (description, then duration and cost, as its notes); its notes
  (comments) and contacts move to the day; the section goes. One with a confirmation becomes a **note**
  instead (retire-old-section-types S1: a confirmation can't cover a whole choice, and nothing is left
  over): the prompt as its heading, its summary, then each option as a "• title — description (duration
  · cost)" paragraph, on the same row, so its confirmation, comments and contacts stay with it;
* a decision to-do (``BookingTask.kind == "decide"`` with options): on the task's day, else its leg's,
  stay's or activity's day, else Day 1 (flagged "check the day"); prompt = its title; each option's
  detail, link and cost carried over; a chosen option is kept as picked. The to-do is ticked off with
  a note saying where its choice went (its options stay readable on it).

``plan(trip)`` lists what would change, by day, without saving; ``apply(trip, keys)`` converts the chosen
ones (``"section-<id>"`` / ``"task-<id>"``; plain ids are sections) in one transaction under one history
line. ``trips:trip_convert`` (the review page), ``manage.py convert_day_first`` and ``import_itinerary
--apply`` (everything, for a new trip) call them; ``pending_count`` is the trip page's banner number.
"""
from dataclasses import dataclass, field

from django.db import transaction

from .models import BookingTask, Section

TONES = {"info": "tip", "tip": "tip", "warning": "warning", "critical": "critical"}


@dataclass
class Conversion:
    """A phase, callout or free text → a note."""
    section: Section
    title: str
    content: dict

    @property
    def key(self):
        return f"section-{self.section.pk}"

    @property
    def before(self):
        """The section as it reads now, in one line per part."""
        s, c = self.section, self.section.content if isinstance(self.section.content, dict) else {}
        kind = s.get_section_type_display()
        if s.section_type == Section.Type.PHASE:
            parts = [c.get("heading") or s.title, c.get("summary") or "", *(f"• {h}" for h in c.get("highlights") or [])]
        elif s.section_type == Section.Type.CALLOUT:
            parts = [f"{s.title}: {c.get('text') or ''}" if s.title else c.get("text") or "", f"({c.get('tone') or 'info'})"]
        elif s.section_type == Section.Type.CHOOSE_YOUR_ADVENTURE:
            parts = [c.get("prompt") or s.title, *(f"• {o.get('title')}" for o in c.get("options") or []
                                                   if isinstance(o, dict))]
        else:
            parts = [s.title, *(c.get("paragraphs") or [])]
        return kind, [p for p in parts if p]

    @property
    def after(self):
        tone = self.content.get("tone")
        head = [f"{self.title}" + (f" ({tone})" if tone else "")] if self.title or tone else []
        return "Note", head + list(self.content.get("paragraphs") or [])


@dataclass
class ChoiceConversion:
    """A choose-your-adventure section or a decision to-do → a "choose one" group (P4)."""
    source: object  # Section or BookingTask
    day: object
    prompt: str
    notes: str
    options: list  # [{"title", "notes", "url", "est_cost", "currency", "order", "chosen"}]
    flag: str = ""  # something to check by hand ("no day: put on Day 1")
    blocked: str = ""  # why it can't be converted (left as it is)
    extra: dict = field(default_factory=dict)

    @property
    def key(self):
        return f"{'task' if isinstance(self.source, BookingTask) else 'section'}-{self.source.pk}"

    @property
    def before(self):
        if isinstance(self.source, BookingTask):
            return "Decision to-do", [self.source.title, *(f"• {o['title']}" + (" ✓" if o["chosen"] else "")
                                                            for o in self.options)]
        return "Choose your adventure", [self.prompt, *(f"• {o['title']}" for o in self.options)]

    @property
    def after(self):
        chosen = next((o["title"] for o in self.options if o["chosen"]), None)
        head = f"{self.prompt}" + (f" (picked: {chosen})" if chosen else " (undecided)")
        return "Choose one", [head, *(f"• {o['title']}" + (f" — {o['notes']}" if o["notes"] else "")
                                      for o in self.options)]


def _as_note(section):
    content = dict(section.content) if isinstance(section.content, dict) else {}
    title = section.title or ""
    if section.section_type == Section.Type.PHASE:
        title = (content.pop("heading", "") or title)[:200]
        paragraphs = [p for p in [content.pop("summary", "")] if p] + [f"• {h}" for h in content.pop("highlights", []) or []]
        tone = ""
    elif section.section_type == Section.Type.CALLOUT:
        text = content.pop("text", "") or ""
        tone = TONES.get(content.pop("tone", "") or "info", "tip")
        paragraphs = [line for line in text.split("\n") if line.strip()]
    else:
        paragraphs = list(content.pop("paragraphs", []) or [])
        tone = ""
    content.update({"tone": tone, "paragraphs": paragraphs})
    return title, content


def _adventure_note(section):
    """A choose-your-adventure section that can't become a group (it has a confirmation) as a note:
    (title, content)."""
    content = dict(section.content) if isinstance(section.content, dict) else {}
    title = (content.pop("prompt", "") or section.title or "Choose one")[:200]
    paragraphs = [p for p in [content.pop("summary", "") or ""] if p]
    for option in content.pop("options", []) or []:
        if not isinstance(option, dict):
            continue
        line = f"• {option.get('title') or 'Option'}"
        if option.get("description"):
            line += f" — {option['description']}"
        extra = " · ".join(str(option.get(k)) for k in ("duration", "cost") if option.get(k))
        if extra:
            line += f" ({extra})"
        paragraphs.append(line)
    content.update({"tone": "", "paragraphs": paragraphs})
    return title, content


def _from_adventure(section, day):
    if section.confirmation_links.exists():
        return Conversion(section, *_adventure_note(section))
    content = section.content if isinstance(section.content, dict) else {}
    options = []
    for order, option in enumerate(content.get("options") or []):
        if not isinstance(option, dict):
            continue
        extra = " · ".join(str(option.get(k)) for k in ("duration", "cost") if option.get(k))
        notes = "\n".join(p for p in (str(option.get("description") or ""), extra) if p)
        options.append({"title": (str(option.get("title") or "") or f"Option {order + 1}")[:200], "notes": notes,
                        "url": "", "est_cost": None, "currency": "", "order": order, "chosen": False})
    return ChoiceConversion(section, day, (content.get("prompt") or section.title or "Choose one")[:200],
                            content.get("summary") or "", options)


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


def pending(sections):
    """The sections (already loaded) that would become notes."""
    return [s for s in sections if s.section_type in Section.OLD_NOTE_TYPES]


def pending_count(trip):
    """Everything still to convert, from the trip page's prefetch (no query): old note sections,
    choose-your-adventure sections, and open decision to-dos with options."""
    sections = [s for d in trip.days.all() for s in getattr(d, "ordered_sections", [])]
    return (len(pending(sections))
            + sum(1 for s in sections if s.section_type == Section.Type.CHOOSE_YOUR_ADVENTURE)
            + sum(1 for t in trip.booking_tasks.all()
                  if t.kind == BookingTask.Kind.DECIDE and not t.done and t.options.all()))


def _decisions(trip):
    return list(trip.booking_tasks.filter(kind=BookingTask.Kind.DECIDE, done=False)
                .select_related("leg", "stay", "activity__day").prefetch_related("options"))


def plan(trip):
    """[(day, [Conversion | ChoiceConversion, …]), …] in day order, for everything still to convert."""
    days = list(trip.days.order_by("date", "day_number").prefetch_related("sections"))
    by_day = {day.pk: [] for day in days}
    for day in days:
        sections = sorted(day.sections.all(), key=lambda s: (s.order, s.pk))
        for section in sections:
            if section.section_type in Section.OLD_NOTE_TYPES:
                by_day[day.pk].append(Conversion(section, *_as_note(section)))
            elif section.section_type == Section.Type.CHOOSE_YOUR_ADVENTURE:
                by_day[day.pk].append(_from_adventure(section, day))
    for task in _decisions(trip):
        if task.options.all():
            conversion = _from_task(task, days)
            if conversion.day is not None:
                by_day[conversion.day.pk].append(conversion)
    return [(day, by_day[day.pk]) for day in days if by_day[day.pk]]


def _make_group(trip, conversion):
    from .models import Comment, ItemLink, Option, OptionGroup
    from django.contrib.contenttypes.models import ContentType
    source = conversion.source
    group = OptionGroup.objects.create(
        trip=trip, day=conversion.day, prompt=conversion.prompt, notes=conversion.notes,
        order=source.order if isinstance(source, Section) else conversion.day.option_groups.count())
    chosen = None
    for data in conversion.options:
        option = Option.objects.create(group=group, title=data["title"], notes=data["notes"], url=data["url"] or "",
                                       est_cost=data["est_cost"], currency=data["currency"] or "", order=data["order"])
        if data["chosen"]:
            chosen = option
    if chosen is not None:
        group.pick(chosen)
    if isinstance(source, BookingTask):
        note = f"Moved to the choice “{group.prompt}” on Day {conversion.day.day_number}."
        source.done = True
        source.notes = "\n".join(p for p in (source.notes, note) if p)
        source.save(update_fields=["done", "notes"])
    else:
        # Its notes (comments) and contacts move to the day it was on; the section goes.
        Comment.objects.filter(content_type=ContentType.objects.get_for_model(Section), object_id=source.pk).update(
            content_type=ContentType.objects.get_for_model(type(conversion.day)), object_id=conversion.day.pk)
        for link in ItemLink.objects.filter(target_type=ContentType.objects.get_for_model(Section), target_id=source.pk):
            ItemLink.link(link.source, conversion.day)
        source.delete()
    return group


def apply(trip, keys=None):
    """Convert the chosen ones (every one when ``keys`` is None); returns how many."""
    from .changes import batch
    wanted = None if keys is None else {k if isinstance(k, str) else f"section-{k}" for k in keys}
    count = 0
    with transaction.atomic(), batch("Converted to notes and choices", trip=trip):
        for _day, conversions in plan(trip):
            for conversion in conversions:
                if wanted is not None and conversion.key not in wanted:
                    continue
                if isinstance(conversion, Conversion):
                    section = conversion.section
                    section.title, section.content = conversion.title, conversion.content
                    section.section_type = Section.Type.NOTE
                    section.save(update_fields=["title", "content", "section_type"])
                elif conversion.blocked:
                    continue
                else:
                    _make_group(trip, conversion)
                count += 1
    return count
