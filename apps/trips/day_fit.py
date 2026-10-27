"""Fit the days to new trip dates (day-first plan, P7): after Settings changes the start or end date.

``plan(trip)`` lists the dates in the trip's range that have no day (``missing``) and the days whose date
falls outside it (``outside``, each with what's on it). Nothing changes until ``apply(trip, add, remove)``:
it makes days for the ``add`` dates, deletes the ``remove`` days (their meals, notes, activities and
choices go with them; journeys and stays aren't tied to a day and stay on the trip) and numbers every
day again in date order. One transaction, one history line.
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Count

from .models import Day, Lodging, TransportLeg


def plan(trip):
    if not trip.start_date or not trip.end_date or trip.end_date < trip.start_date:
        return {"missing": [], "outside": []}
    days = list(trip.days.annotate(meal_count=Count("meals", distinct=True),
                                   section_count=Count("sections", distinct=True),
                                   activity_count=Count("activities", distinct=True),
                                   group_count=Count("option_groups", distinct=True)))
    have = {day.date for day in days if day.date}
    span = (trip.end_date - trip.start_date).days + 1
    missing = [trip.start_date + timedelta(days=n) for n in range(span)
               if trip.start_date + timedelta(days=n) not in have]
    outside = [day for day in days if day.date and not trip.start_date <= day.date <= trip.end_date]
    if outside:
        dates = [day.date for day in outside]
        legs = set(TransportLeg.objects.filter(trip=trip, date__in=dates).values_list("date", flat=True))
        stays = set(Lodging.objects.filter(trip=trip, check_in__in=dates).values_list("check_in", flat=True))
        for day in outside:
            parts = [(day.meal_count, "meal", "meals"), (day.activity_count, "activity", "activities"),
                     (day.section_count, "note", "notes"), (day.group_count, "choice", "choices")]
            day.contents = [f"{n} {one if n == 1 else many}" for n, one, many in parts if n]
            day.has_bookings = day.date in legs or day.date in stays
            day.is_empty = not day.contents
    return {"missing": missing, "outside": outside}


def renumber(trip):
    """Day 1, 2, … in date order (days without a date last), in two passes so the unique
    (trip, day number) never clashes on the way."""
    days = sorted(trip.days.all(), key=lambda d: (d.date is None, d.date or trip.start_date, d.day_number))
    for n, day in enumerate(days, start=1):
        Day.objects.filter(pk=day.pk).update(day_number=10000 + n)
    for n, day in enumerate(days, start=1):
        Day.objects.filter(pk=day.pk).update(day_number=n)


def apply(trip, add=(), remove=()):
    """Make days for ``add`` dates and delete the ``remove`` days (only ones outside the dates). Returns
    (made, removed)."""
    from .changes import batch
    found = plan(trip)
    add = [d for d in add if d in set(found["missing"])]
    remove = [day for day in found["outside"] if day.pk in set(remove)]
    if not add and not remove:
        return 0, 0
    with transaction.atomic(), batch("Days fitted to the trip's dates", trip=trip):
        for day in remove:
            day.delete()
        top = max(trip.days.values_list("day_number", flat=True), default=0)
        for n, when in enumerate(sorted(add), start=1):
            Day.objects.create(trip=trip, day_number=top + n, date=when)
        renumber(trip)
    return len(add), len(remove)
