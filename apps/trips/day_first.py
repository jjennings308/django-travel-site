"""Converting a trip's old sections to the day-first kinds (day-first plan, decision 6), on review.

P3: phases, callouts and free text become **notes** (``Section.Type.NOTE``, payload ``{"tone",
"paragraphs"}``; the heading is the section's ``title``):

* a phase: heading (its ``heading``, else its title), then its summary as a paragraph and each highlight
  as a "• " paragraph;
* a callout: its title and text, its tone kept (info → tip);
* free text: its title and paragraphs.

Other keys in the payload are kept, as the payload forms keep them, so nothing an importer wrote is lost.
``plan(trip)`` lists what would change, by day, without saving; ``apply(trip, ids)`` converts the chosen
sections in one transaction under one history line. ``trips:trip_convert`` (the review page),
``manage.py convert_day_first`` and ``import_itinerary --apply`` (everything, for a new trip) call them.
"""
from dataclasses import dataclass

from django.db import transaction

from .models import Section

TONES = {"info": "tip", "tip": "tip", "warning": "warning", "critical": "critical"}


@dataclass
class Conversion:
    section: Section
    title: str
    content: dict

    @property
    def before(self):
        """The section as it reads now, in one line per part."""
        s, c = self.section, self.section.content if isinstance(self.section.content, dict) else {}
        kind = s.get_section_type_display()
        if s.section_type == Section.Type.PHASE:
            parts = [c.get("heading") or s.title, c.get("summary") or "", *(f"• {h}" for h in c.get("highlights") or [])]
        elif s.section_type == Section.Type.CALLOUT:
            parts = [f"{s.title}: {c.get('text') or ''}" if s.title else c.get("text") or "", f"({c.get('tone') or 'info'})"]
        else:
            parts = [s.title, *(c.get("paragraphs") or [])]
        return kind, [p for p in parts if p]

    @property
    def after(self):
        tone = self.content.get("tone")
        head = [f"{self.title}" + (f" ({tone})" if tone else "")] if self.title or tone else []
        return "Note", head + list(self.content.get("paragraphs") or [])


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


def pending(sections):
    """The sections (already loaded) that would be converted."""
    return [s for s in sections if s.section_type in Section.OLD_NOTE_TYPES]


def plan(trip):
    """[(day, [Conversion, …]), …] in day order, for the sections still to convert."""
    days = list(trip.days.order_by("date", "day_number").prefetch_related("sections"))
    found = []
    for day in days:
        sections = sorted(pending(day.sections.all()), key=lambda s: (s.order, s.pk))
        if sections:
            found.append((day, [Conversion(s, *_as_note(s)) for s in sections]))
    return found


def apply(trip, ids=None):
    """Convert the old sections with these ids (every one when ``ids`` is None); returns how many."""
    from .changes import batch
    sections = Section.objects.filter(day__trip=trip, section_type__in=Section.OLD_NOTE_TYPES)
    if ids is not None:
        sections = sections.filter(pk__in=ids)
    count = 0
    with transaction.atomic(), batch("Turned phases, callouts and free text into notes", trip=trip):
        for section in sections.select_for_update():
            section.title, section.content = _as_note(section)
            section.section_type = Section.Type.NOTE
            section.save(update_fields=["title", "content", "section_type"])
            count += 1
    return count
