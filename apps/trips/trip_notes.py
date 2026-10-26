"""Catalogue notes on a trip (catalogue-notes plan, N2).

A meal, a trip activity or a section linked to the catalogue (``Meal.poi``, ``TripActivity.poi``,
``Section.poi`` / ``Section.activity``, R18) shows that place's or activity's approved notes under it, on the
trip page and in the booklet; a section linked to an activity also gets its venue's. ``attach`` reads the
trip page's prefetch (the days' ``ordered_meals`` / ``ordered_activities`` / ``ordered_sections``) and loads
every note in **one** query, with whether this trip hides it ("Not for this trip", ``TripHiddenNote``):
``item.trip_notes`` (shown) and ``item.hidden_trip_notes`` (for editors, to show again). Each note carries
``from_name``, the place or activity it comes from.
"""
from django.db.models import Exists, OuterRef, Q

from apps.approval_system.models import ApprovalStatus
from apps.catalogue_notes.models import CatalogueNote

from .models import TripHiddenNote


def _sources(item):
    """(note field, pk, name) for an item's catalogue targets, in the order their notes show."""
    found = []
    activity = getattr(item, "activity", None) if getattr(item, "activity_id", None) else None
    if activity is not None:  # a section linked to a catalogue activity: its notes, then its venue's
        found.append(("activity_id", activity.pk, activity.name))
        if activity.venue_id:
            found.append(("poi_id", activity.venue_id, None))
    if getattr(item, "poi_id", None):
        found.append(("poi_id", item.poi_id, item.poi.name))
    return found


def items_of(days):
    """Every meal, trip activity and section of these days (the trip page's prefetched lists)."""
    for day in days:
        yield from getattr(day, "ordered_meals", [])
        yield from getattr(day, "ordered_activities", [])
        yield from getattr(day, "ordered_sections", [])


def attach(trip, days):
    items = list(items_of(days))
    wanted = {item: _sources(item) for item in items}
    poi_ids = {pk for found in wanted.values() for field, pk, _ in found if field == "poi_id"}
    activity_ids = {pk for found in wanted.values() for field, pk, _ in found if field == "activity_id"}
    notes = []
    if poi_ids or activity_ids:
        notes = list(
            CatalogueNote.objects.filter(Q(poi_id__in=poi_ids) | Q(activity_id__in=activity_ids),
                                         approval_status=ApprovalStatus.APPROVED)
            .select_related("poi")
            .annotate(hidden=Exists(TripHiddenNote.objects.filter(trip=trip, note=OuterRef("pk")))))
    for item, found in wanted.items():
        shown, hidden, seen = [], [], set()
        for field, pk, name in found:
            for note in notes:
                if getattr(note, field) != pk or note.pk in seen:
                    continue
                seen.add(note.pk)
                note.from_name = name or (note.poi.name if note.poi_id else "")
                (hidden if note.hidden else shown).append(note)
        item.trip_notes, item.hidden_trip_notes = shown, hidden
