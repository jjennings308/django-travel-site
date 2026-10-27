"""The route builder and the route strip (day-first plan, P1).

A route is a list of stops, each a city and a number of nights ("Munich 3 → Salzburg 2 → Vienna 4").
``plan`` lays it over the trip's dates: stop 1 covers the first ``nights`` days, stop 2 starts on the
changeover day (the day you travel), and the last stop also has the departure day, so a route adds up
when its nights equal the trip's. ``apply`` saves a plan in one transaction under one history line:
each day's city (a day that already has a different one is kept unless ``replace``), a planned leg on
each changeover day (``make_legs``; skipped when that day already has a leg between the two cities)
and a placeholder stay per stop (``make_stays``: "Stay in Munich", no address, so it shows in Not
booked yet; skipped when a stay already covers any of those nights). A route longer than the trip is
cut at its end unless ``extend`` moves the end date; a shorter one leaves the last days blank.

``runs(days)`` is the other direction, for the trip page's strip and the builder's first rows: the days'
cities as consecutive runs.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction


@dataclass
class Run:
    city: object
    days: list

    @property
    def first(self):
        return self.days[0]


def runs(days):
    """Consecutive days (by date, else number) with the same city, blank days skipped:
    [Run(city, [day, …]), …]. No queries: reads ``day.city`` (select_related on the trip page)."""
    found = []
    ordered = sorted(days, key=lambda d: (d.date is None, d.date or 0, d.day_number))
    previous = None
    for day in ordered:
        if not day.city_id:
            previous = None
            continue
        if previous is not None and previous.city.pk == day.city_id:
            previous.days.append(day)
        else:
            previous = Run(day.city, [day])
            found.append(previous)
    return found


def initial_stops(days, end_date):
    """The builder's first rows, from the days' cities: nights = days in the run, less the
    departure day when the run reaches the trip's last day."""
    stops = []
    for run in runs(days):
        nights = len(run.days)
        if end_date and run.days[-1].date == end_date:
            nights -= 1
        stops.append({"city": run.city, "nights": max(nights, 1)})
    return stops


@dataclass
class Plan:
    stops: list                                   # [(city, nights)]
    dates: list                                   # every date the route covers, with its city
    days_set: list = field(default_factory=list)  # (date, day or None, city): blank days to fill / days to make
    conflicts: list = field(default_factory=list) # (date, day, its city, route city): kept unless replace
    legs: list = field(default_factory=list)      # (date, from city, to city, already there)
    stays: list = field(default_factory=list)     # (city, check_in, check_out, already covered by)
    route_nights: int = 0
    trip_nights: int = 0
    new_end: object = None                        # the end date when extending
    cut: bool = False                             # longer than the trip, not extended
    blank_from: object = None                     # shorter: days from here on stay blank

    @property
    def summary(self):
        return " → ".join(f"{city.name} ({nights})" for city, nights in self.stops)


def plan(trip, stops, days, legs, stays, extend=False):
    """Lay ``stops`` [(city, nights)] over ``trip``'s dates. ``days``, ``legs`` and ``stays`` are
    the trip's current rows (lists); nothing is saved."""
    result = Plan(stops=stops, dates=[])
    if not stops or not trip.start_date:
        return result
    result.route_nights = sum(nights for _, nights in stops)
    end = trip.end_date or trip.start_date
    result.trip_nights = (end - trip.start_date).days
    if result.route_nights > result.trip_nights:
        if extend:
            end = trip.start_date + timedelta(days=result.route_nights)
            result.new_end = end
        else:
            result.cut = True
    last_date = end
    when = trip.start_date
    starts = []
    for city, nights in stops:
        if when > last_date:
            break
        starts.append((city, when, nights))
        for _ in range(nights):
            if when > last_date:
                break
            result.dates.append((when, city))
            when += timedelta(days=1)
    if when == last_date and starts:  # the departure day belongs to the last stop
        result.dates.append((when, starts[-1][0]))
    elif when < last_date:
        result.blank_from = when
    by_date = {day.date: day for day in days if day.date}
    for date, city in result.dates:
        day = by_date.get(date)
        if day is not None and day.city_id and day.city_id != city.pk:
            result.conflicts.append((date, day, day.city, city))
        elif day is None or day.city_id != city.pk:
            result.days_set.append((date, day, city))
    for (city_a, _, _), (city_b, changeover, _) in zip(starts, starts[1:]):
        if city_a.pk == city_b.pk:
            continue
        there = any(leg.date == changeover and leg.origin_city_id == city_a.pk
                    and leg.destination_city_id == city_b.pk for leg in legs)
        result.legs.append((changeover, city_a, city_b, there))
    for city, check_in, nights in starts:
        check_out = min(check_in + timedelta(days=nights), last_date)
        if check_out <= check_in:
            continue
        covered = next((stay for stay in stays if stay.check_in < check_out and stay.check_out > check_in), None)
        result.stays.append((city, check_in, check_out, covered))
    return result


def apply(trip, route, replace=False, make_legs=True, make_stays=True):
    """Save ``route`` (a ``Plan``). Returns counts: days set, days made, legs, stays."""
    from . import currencies, trip_cities
    from .changes import batch
    from .models import Day, Lodging, TransportLeg
    counts = {"days": 0, "new_days": 0, "legs": 0, "stays": 0}
    with transaction.atomic(), batch(f"Route set: {route.summary}", trip=trip):
        if route.new_end and route.new_end != trip.end_date:
            trip.end_date = route.new_end
            trip.save(update_fields=["end_date"])
        targets = list(route.days_set) + ([(date, day, city) for date, day, _, city in route.conflicts]
                                          if replace else [])
        taken = set(trip.days.values_list("day_number", flat=True))
        for date, day, city in sorted(targets, key=lambda t: t[0]):
            if day is None:
                number = (date - trip.start_date).days + 1
                if number in taken or number < 1:
                    number = max(taken | {0}) + 1
                taken.add(number)
                Day.objects.create(trip=trip, day_number=number, date=date, city=city)
                counts["new_days"] += 1
            else:
                day.city = city
                day.save(update_fields=["city"])
                counts["days"] += 1
        if make_legs:
            for date, city_a, city_b, there in route.legs:
                if there:
                    continue
                TransportLeg.objects.create(
                    trip=trip, date=date, mode=TransportLeg.Mode.OTHER, origin=city_a.name, destination=city_b.name,
                    origin_city=city_a, destination_city=city_b, origin_timezone=city_a.timezone or "",
                    destination_timezone=city_b.timezone or "",
                    currency=currencies.default_for(trip, [city_a.pk, city_b.pk]))
                counts["legs"] += 1
        if make_stays:
            for city, check_in, check_out, covered in route.stays:
                if covered is not None:
                    continue
                Lodging.objects.create(trip=trip, name=f"Stay in {city.name}", city=city, check_in=check_in,
                                       check_out=check_out, currency=currencies.default_for(trip, [city.pk]))
                counts["stays"] += 1
        trip_cities.sync(trip)
    return counts
