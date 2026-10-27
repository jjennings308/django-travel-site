"""A trip's cities keep themselves up to date (day-first plan, P1).

``Trip.cities`` is the list the city boxes offer first ("This trip"), the trip map's pins and the
visitor counts' source. ``sync(trip)`` adds every city something on the trip uses: a day's city, a
stay's, either end of a leg, and the city of the catalogue place or event linked to a trip activity,
a meal or a section, and the place of an idea on the shelf (P6). It never removes one on its own; Settings removes a city only when nothing uses
it (``used_by`` says what does: "Day 3, Hotel Laimer Hof"). Called after the trip's forms save, and by
the leg quick add, the table conversion, the stays' day fill and the route builder.
"""
from .models import Day, Lodging, Meal, Section, TransportLeg, TripActivity


def _uses(trip):
    """(city id, what uses it) pairs, a handful of queries whatever the trip's size."""
    for number, city_id in Day.objects.filter(trip=trip, city__isnull=False).values_list("day_number", "city_id"):
        yield city_id, f"Day {number}"
    for name, city_id in Lodging.objects.filter(trip=trip, city__isnull=False).values_list("name", "city_id"):
        yield city_id, name or "A stay"
    for origin, destination, a, b in (TransportLeg.objects.filter(trip=trip)
                                      .exclude(origin_city__isnull=True, destination_city__isnull=True)
                                      .values_list("origin", "destination", "origin_city_id", "destination_city_id")):
        for city_id in (a, b):
            if city_id:
                yield city_id, f"{origin} → {destination}"
    linked = (
        (TripActivity.objects.filter(trip=trip), "title"),
        (Meal.objects.filter(day__trip=trip), "name"),
        (Section.objects.filter(day__trip=trip), "title"),
    )
    for queryset, label in linked:
        rows = (queryset.exclude(poi__isnull=True, event__isnull=True) if hasattr(queryset.model, "event")
                else queryset.exclude(poi__isnull=True))
        fields = [label, "poi__city_id"] + (["event__city_id"] if hasattr(queryset.model, "event") else [])
        for name, *city_ids in rows.values_list(*fields):
            for city_id in city_ids:
                if city_id:
                    yield city_id, name or "An item"
    from .ideas import city_ids
    for city_id, title in city_ids(trip):
        yield city_id, f"the idea “{title}”"


def used_by(trip):
    """{city id: [what uses it, …]} for the trip's cities that something on it uses."""
    found = {}
    for city_id, label in _uses(trip):
        labels = found.setdefault(city_id, [])
        if label not in labels:
            labels.append(label)
    return found


def sync(trip):
    """Add to ``trip.cities`` every city something on the trip uses; returns how many were added."""
    if trip is None or not trip.pk:
        return 0
    missing = {city_id for city_id, _ in _uses(trip)} - set(trip.cities.values_list("pk", flat=True))
    if missing:
        trip.cities.add(*missing)
    return len(missing)
