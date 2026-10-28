"""Catalogue notes on a trip (catalogue-notes plan, N2).

A meal, a trip activity or a section linked to the catalogue (``Meal.poi``, ``TripActivity.poi`` /
``.event``, ``Section.poi`` / ``.activity`` / ``.event``; R18, N4) shows those items' approved notes under it,
on the trip page and in the booklet: an event's own, then its activity's and its venue's; a section's
activity's, then that activity's venue's; then the item's own place. ``attach`` reads the
trip page's prefetch (the days' ``ordered_meals`` / ``ordered_activities`` / ``ordered_sections``) and loads
every note in **one** query, with whether this trip hides it ("Not for this trip", ``TripHiddenNote``):
``item.trip_notes`` (shown) and ``item.hidden_trip_notes`` (for editors, to show again). Each note carries
``from_name``, the place or activity it comes from. An undecided choice's options linked to the catalogue
(typed-choices T3) get theirs in the same query, shown folded under the option ("2 notes").

A city's notes ("Most shops close on Sundays") come through where the trip is in that city: the first day of each
run of days spent there (``route.runs``: Munich Days 3–5 shows them on Day 3, under the stay) and a stay option
whose city it is. Same query, same "Not for this trip".
"""
from django.db.models import Exists, OuterRef, Q

from apps.approval_system.models import ApprovalStatus
from apps.catalogue_notes.models import CatalogueNote

from .models import TripHiddenNote
from .route import runs


def _sources(item):
    """(note field, pk, name) for an item's catalogue targets, in the order their notes show."""
    found = []
    event = getattr(item, "event", None) if getattr(item, "event_id", None) else None
    if event is not None:  # an event: its notes, then its activity's and its venue's (N4)
        found.append(("event_id", event.pk, event.name))
        if event.related_activity_id:
            found.append(("activity_id", event.related_activity_id, event.related_activity.name))
        if event.poi_id:
            found.append(("poi_id", event.poi_id, event.poi.name))
    activity = getattr(item, "activity", None) if getattr(item, "activity_id", None) else None
    if activity is not None:  # a section linked to a catalogue activity: its notes, then its venue's
        found.append(("activity_id", activity.pk, activity.name))
        if activity.venue_id:
            found.append(("poi_id", activity.venue_id, None))
    if getattr(item, "poi_id", None):
        found.append(("poi_id", item.poi_id, item.poi.name))
    if getattr(item, "city_id", None):  # a day (the first of a run in the city) or a stay option
        found.append(("city_id", item.city_id, item.city.name))
    return found


def items_of(days):
    """Every meal, trip activity and section of these days (the trip page's prefetched lists), and the
    options of their undecided choices (typed-choices T3: a catalogue-linked option shows its notes while
    you decide; ``options.attach`` runs first and sets ``day.open_groups``)."""
    for day in days:
        yield from getattr(day, "ordered_meals", [])
        yield from getattr(day, "ordered_activities", [])
        yield from getattr(day, "ordered_sections", [])
        for group in getattr(day, "open_groups", []):
            yield from getattr(group, "option_list", [])


def attach(trip, days):
    first_days = [run.days[0] for run in runs(days)]
    for day in days:
        day.trip_notes, day.hidden_trip_notes = [], []
    items = [*items_of(days), *first_days]
    wanted = {item: _sources(item) for item in items}
    ids = {field: {pk for found in wanted.values() for name, pk, _ in found if name == field}
           for field in ("poi_id", "activity_id", "event_id", "city_id")}
    notes = []
    if any(ids.values()):
        notes = list(
            CatalogueNote.objects.filter(Q(poi_id__in=ids["poi_id"]) | Q(activity_id__in=ids["activity_id"])
                                         | Q(event_id__in=ids["event_id"]) | Q(city_id__in=ids["city_id"]),
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
