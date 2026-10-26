"""How many live trips use each catalogue place, activity and event (site roadmap R18; events added after
catalogue-notes N4).

A place counts a trip with a meal, section or day activity there; an activity counts a trip with a
section linked to it; an event counts a trip with a section or day activity linked to it, and that trip
also counts for the event's activity and its venue (as their notes come through). Each trip counts once,
deleted trips never. Stored on ``POI.trip_count`` / ``Activity.trip_count`` / ``Event.trip_count`` so
pages pay no query; ``recount()`` runs nightly from ``recount_visitors``.
Pages show the number only from ``TRIP_COUNT_MIN`` and never say which trips.
"""
from collections import defaultdict

from django.db import transaction

from apps.activities.models import Activity
from apps.events.models import Event
from apps.locations.models import POI

from .models import Meal, Section, TripActivity


def _trips_per(rows):
    seen = defaultdict(set)
    for target_id, trip_id in rows:
        if target_id:
            seen[target_id].add(trip_id)
    return {target_id: len(trips) for target_id, trips in seen.items()}


LIVE_DAY = {"day__trip__deleted_at__isnull": True}
LIVE_TRIP = {"trip__deleted_at__isnull": True}


def _event_rows(field):
    """(``field`` of the linked event, trip id) for every section and day activity linked to an event."""
    return [*Section.objects.filter(event__isnull=False, **LIVE_DAY).values_list(f"event__{field}", "day__trip_id"),
            *TripActivity.objects.filter(event__isnull=False, **LIVE_TRIP).values_list(f"event__{field}", "trip_id")]


def place_counts():
    rows = [*Meal.objects.filter(poi__isnull=False, **LIVE_DAY).values_list("poi_id", "day__trip_id"),
            *Section.objects.filter(poi__isnull=False, **LIVE_DAY).values_list("poi_id", "day__trip_id"),
            *TripActivity.objects.filter(poi__isnull=False, **LIVE_TRIP).values_list("poi_id", "trip_id"),
            *_event_rows("poi_id")]
    return _trips_per(rows)


def activity_counts():
    return _trips_per([*Section.objects.filter(activity__isnull=False, **LIVE_DAY)
                       .values_list("activity_id", "day__trip_id"),
                       *_event_rows("related_activity_id")])


def event_counts():
    return _trips_per(_event_rows("id"))


def _store(model, counts):
    changed = model.objects.filter(trip_count__gt=0).exclude(pk__in=counts).update(trip_count=0)
    stored = dict(model.objects.filter(pk__in=counts).values_list("pk", "trip_count"))
    for pk, count in counts.items():
        if stored.get(pk, count) != count:
            model.objects.filter(pk=pk).update(trip_count=count)
            changed += 1
    return changed


@transaction.atomic
def recount():
    """Recompute every stored count; returns how many changed."""
    return (_store(POI, place_counts()) + _store(Activity, activity_counts())
            + _store(Event, event_counts()))
