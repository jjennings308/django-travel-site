"""The old section types as day-first kinds.

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

Decision to-dos (a to-do with options) were converted into groups here until retire-decision-todos D2
removed them; ``make_group`` is what's left of that, used by ``import_itinerary`` and Tidy.
"""
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
