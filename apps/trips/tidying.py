"""The Django side of content clean-up (docs/plans/trip-page-ux.md, U7): ``snapshot(trip)`` turns
a trip into the plain data ``tidy.suggest`` reads, and ``apply(trip, suggestions, chosen)``
carries out the ticked suggestions in one transaction. Each change is re-checked against the
current data first; a suggestion whose text has changed since it was made is skipped, not forced.
"""
import re

from django.db import transaction

from . import tidy
from .models import (BookingTask, Confirmation, Contact, ItemLink, LINKABLE, Meal, Section, TaskOption, TidyDismissal,
                     TripInfo)


def snapshot(trip):
    """The plain data ``tidy.suggest`` reads (see its docstring)."""
    days = list(trip.days.order_by("date", "day_number"))
    legs = list(trip.transport.all())
    stays = list(trip.lodging.all())
    activities = list(trip.activities.all())
    meals = list(Meal.objects.filter(day__trip=trip).order_by("order", "id"))
    sections = list(Section.objects.filter(day__trip=trip).order_by("order", "id"))
    plain_days = []
    for day in days:
        plain_sections = []
        for s in (s for s in sections if s.day_id == day.pk):
            c = s.content if isinstance(s.content, dict) else {}
            plain_sections.append({
                "id": s.pk, "type": s.section_type, "title": s.title, "heading": c.get("heading") or "",
                "summary": c.get("summary") or "", "highlights": list(c.get("highlights") or []),
                "paragraphs": list(c.get("paragraphs") or []), "text": c.get("text") or "",
                "columns": list(c.get("columns") or []), "rows": [list(r) for r in c.get("rows") or []]})
        plain_days.append({
            "id": day.pk, "number": day.day_number, "date": day.date, "sections": plain_sections,
            "legs": [{"id": l.pk, "origin": l.origin, "destination": l.destination}
                     for l in legs if l.date and l.date == day.date],
            "stays": [{"id": st.pk, "name": st.name} for st in stays if day.date in (st.check_in, st.check_out)],
            "meals": [{"id": m.pk, "name": m.name, "notes": m.reservation_notes, "type": m.meal_type,
                       "time": m.reserved_time.strftime("%H:%M") if m.reserved_time else None}
                      for m in meals if m.day_id == day.pk],
            "activities": [{"id": a.pk, "title": a.title} for a in activities if a.day_id == day.pk]})
    tasks = []
    for task in trip.booking_tasks.filter(done=False).select_related("leg", "stay", "activity"):
        item = None
        if task.leg_id:
            item = {"kind": "leg", "id": task.leg_id, "label": f"{task.leg.origin} → {task.leg.destination}"}
        elif task.stay_id:
            item = {"kind": "stay", "id": task.stay_id, "label": task.stay.name}
        elif task.activity_id:
            item = {"kind": "activity", "id": task.activity_id, "label": task.activity.title}
        tasks.append({"id": task.pk, "title": task.title, "item": item})
    return {
        "notes": trip.notes,
        "days": plain_days,
        "trip_legs": [{"id": l.pk, "origin": l.origin, "destination": l.destination} for l in legs],
        "trip_stays": [{"id": st.pk, "name": st.name} for st in stays],
        "tasks": tasks,
        "known_numbers": list(Confirmation.objects.filter(trip=trip).values_list("confirmation_number", flat=True)),
        "contact_phones": list(trip.contacts.values_list("phone", flat=True)),
    }


def suggestions(trip):
    dismissed = set(TidyDismissal.objects.filter(trip=trip).values_list("key", flat=True))
    return tidy.suggest(snapshot(trip), dismissed)


def dismiss(trip, key):
    TidyDismissal.objects.get_or_create(trip=trip, key=key[:64])


# ---- applying ---------------------------------------------------------------------------
class Stale(Exception):
    """The data changed since the suggestion was made."""


def _section(trip, pk):
    section = Section.objects.filter(day__trip=trip, pk=pk).first()
    if section is None:
        raise Stale("the section is gone")
    return section


def _remove_from_content(section, field, line, replacement=None):
    content = dict(section.content or {})
    if field == "summary" or field == "text":
        if (content.get(field) or "") != line:
            raise Stale("the text changed")
        content[field] = replacement if replacement is not None else ""
    else:
        items = list(content.get(field) or [])
        if line not in items:
            raise Stale("the line changed")
        if replacement is None:
            items.remove(line)
        else:
            items[items.index(line)] = replacement
        content[field] = items
    section.content = content
    section.save(update_fields=["content"])


def _item(trip, ref):
    model = LINKABLE[ref["kind"]]
    item = model.objects.filter(pk=ref["id"]).first()
    if item is None:
        raise Stale("the item is gone")
    return item


def _append_notes(item, text):
    if not text:
        return
    attr = "why_recommended" if isinstance(item, Meal) else "notes"
    current = getattr(item, attr) or ""
    if text not in current:
        setattr(item, attr, "\n".join(p for p in (current, text) if p))
        item.save(update_fields=[attr])


def _apply_one(trip, s, action):
    c = s.change
    op = c["op"]
    if op == "remove_line":
        _remove_from_content(_section(trip, c["section"]), c["field"], c["line"])
        if action == "remove_keep":
            _append_notes(_item(trip, c["item"]), c["extra"])
    elif op == "callout":
        section = _section(trip, c["section"])
        if (section.content or {}).get("text", "") != c["text"]:
            raise Stale("the callout changed")
        if action == "to_info" and c.get("item"):
            title = re.sub(r"^[^\w]+", "", c["title"]).strip() or "Note"
            info = TripInfo.objects.create(trip=trip, title=title[:200], body=c["text"])
            ItemLink.link(info, _item(trip, c["item"]))
        section.delete()
    elif op == "phone":
        place = c["place"]
        if place["type"] == "section":
            section = _section(trip, place["id"])
            content = section.content or {}
            field = place["field"]
            if field in ("summary", "text"):
                current = content.get(field) or ""
            else:
                items = content.get(field) or []
                index = place["index"]
                current = items[index] if index is not None and index < len(items) else ""
            if not current or c["number"] not in current:
                raise Stale("the text changed")
            _remove_from_content(section, field, current, tidy._without(current, c["number"]))
        elif place["type"] == "meal":
            meal = Meal.objects.filter(day__trip=trip, pk=place["id"]).first()
            if meal is None or c["number"] not in meal.reservation_notes:
                raise Stale("the meal's notes changed")
            meal.reservation_notes = tidy._without(meal.reservation_notes, c["number"])
            meal.save(update_fields=["reservation_notes"])
        else:
            if place["line"] not in trip.notes.splitlines():
                raise Stale("the trip notes changed")
            lines = trip.notes.splitlines()
            remove = place.get("remove") or []
            if any(line not in lines for line in remove):
                raise Stale("the trip notes changed")
            if remove:
                for line in remove:
                    lines.remove(line)
            else:
                lines[lines.index(place["line"])] = place["rest"]
            trip.notes = "\n".join(lines).strip()
            trip.save(update_fields=["notes"])
        contact = Contact.objects.create(trip=trip, name=c["name"][:200], phone=c["number"][:40],
                                         notes=c.get("notes", ""))
        if c.get("link"):
            ItemLink.link(contact, _item(trip, c["link"]))
    elif op == "notes_remove":
        lines = trip.notes.splitlines()
        if c["line"] not in lines:
            raise Stale("the trip notes changed")
        lines.remove(c["line"])
        trip.notes = "\n".join(lines).strip()
        trip.save(update_fields=["notes"])
    elif op == "notes_options":
        lines = trip.notes.splitlines()
        if any(line not in lines for line in c["lines"]):
            raise Stale("the trip notes changed")
        task = BookingTask.objects.create(trip=trip, title=c["title"][:200], kind=BookingTask.Kind.DECIDE)
        for order, title in enumerate(c["options"], start=1):
            TaskOption.objects.create(task=task, title=title, order=order)
        for line in c["lines"]:
            lines.remove(line)
        trip.notes = "\n".join(lines).strip()
        trip.save(update_fields=["notes"])
    elif op == "meal_phase":
        section = _section(trip, c["section"])
        content = section.content or {}
        if (section.section_type != "phase" or content.get("summary") or content.get("highlights")
                or (content.get("heading") or section.title) != c["heading"]):
            raise Stale("the phase changed")
        meal = Meal.objects.filter(day__trip=trip, day_id=section.day_id, pk=c["meal"]).first()
        if meal is None:
            raise Stale("the meal is gone")
        if action == "time_remove":
            if meal.reserved_time is not None:
                raise Stale("the meal already has a time")
            from datetime import time as clock
            hours, minutes = map(int, c["time"].split(":"))
            meal.reserved_time = clock(hours, minutes)
            meal.save(update_fields=["reserved_time"])
        section.delete()
    elif op == "table_to_info":
        section = _section(trip, c["section"])
        columns = c["columns"]
        body = "\n\n".join(" · ".join(f"{columns[i]}: {cell}" if i < len(columns) and columns[i] else str(cell)
                                      for i, cell in enumerate(row)) for row in c["rows"])
        info = TripInfo.objects.create(trip=trip, title=c["title"][:200], body=body)
        ItemLink.link(info, _item(trip, {"kind": "activity", "id": c["activity"]}))
        section.delete()
    else:
        raise Stale("nothing to do")


def apply(trip, found, chosen):
    """Carry out ``chosen`` ({key: action}) from ``found`` (this trip's suggestions) in one
    transaction. Returns (applied, skipped) as lists of (suggestion, note). Any error other than
    a stale suggestion rolls the whole batch back."""
    by_key = {s.key: s for s in found}
    from .changes import batch
    applied, skipped = [], []
    with transaction.atomic(), batch("Applied tidy suggestions", trip=trip):
        for key, action in chosen.items():
            s = by_key.get(key)
            if s is None or s.flag_only or action not in dict(s.actions):
                continue
            try:
                with transaction.atomic():
                    _apply_one(trip, s, action)
                applied.append((s, action))
            except Stale as exc:
                skipped.append((s, str(exc)))
    return applied, skipped
