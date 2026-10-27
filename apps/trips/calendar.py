"""A trip as an iCalendar feed (site roadmap R4), served at ``/trips/calendar/<token>.ics``.

One event per item, with a stable ``UID`` (``leg-<pk>@sharebucketlist.com``) so a calendar app
replaces an edited event instead of adding a second:

* a leg with times: UTC start and end (a flight is at one instant wherever you are);
* an activity with a start time, a meal with a reservation time: **floating** local times — the
  wall clock wherever the phone is, which is what a traveller wants (end = ``end_time`` or +1 h);
* a planned leg (no times) and an activity without a time: all day on their day;
* a stay: all day from check-in to check-out (the end date is exclusive, as iCalendar wants).

Descriptions carry the operator, service number and **confirmation numbers** (James, 2026-10-18:
the link is private per person and can be reset), and a link to the item on the trip page.
``mine=True`` keeps what the viewer is on: an activity's own travellers, else — for an item on a
split group's track (day-first plan P5) — its option's travellers, else the day's (``options.on_it``);
legs and meals go by their track, else the day's; blank means everyone; stays show unless they're on
someone else's track; a viewer with no traveller record sees everything. Loading is a fixed number of queries, whatever the trip's size.
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db.models import Prefetch
from django.urls import reverse
from apps.core.ical import DOMAIN, calendar, vevent

from .itinerary import ACTIVITY_ICONS, MODE_ICONS
from .models import (ConfirmationLink, Day, Lodging, Meal, Option, OptionGroup, TransportLeg, Traveler,
                     TripActivity, counts_q)
from .options import on_it

REFRESH = timedelta(hours=4)


def _numbers(confirmations):
    return [f"Confirmation: {c.confirmation_number}{f' ({c.provider})' if c.provider else ''}"
            for c in confirmations]


def load(trip):
    """Everything the feed needs, in a fixed number of queries."""
    days = list(trip.days.prefetch_related("travelers"))
    # Only what counts (day-first plan P4): nothing in an undecided or unchosen option.
    legs = list(TransportLeg.objects.filter(counts_q(), trip=trip))
    activities = list(TripActivity.objects.filter(counts_q(), day__trip=trip).select_related("poi")
                      .prefetch_related(Prefetch("travelers", queryset=Traveler.objects.only("pk"))))
    meals = list(Meal.objects.filter(counts_q(), day__trip=trip).exclude(reserved_time=None))
    stays = list(Lodging.objects.filter(counts_q(), trip=trip))
    found = {}
    for link in ConfirmationLink.objects.filter(confirmation__trip=trip).select_related("confirmation"):
        found.setdefault((link.content_type_id, link.object_id), []).append(link.confirmation)
    # Who takes each option of a split group (P5): its items are theirs.
    tracks = {}
    for row in Option.travelers.through.objects.filter(option__group__trip=trip,
                                                       option__group__state=OptionGroup.State.SPLIT):
        tracks.setdefault(row.option_id, []).append(row.traveler_id)
    types = ContentType.objects.get_for_models(TransportLeg, TripActivity, Meal, Lodging)  # cached after first use
    for model, items in ((TransportLeg, legs), (TripActivity, activities), (Meal, meals), (Lodging, stays)):
        for item in items:
            item.cal_confirmations = found.get((types[model].pk, item.pk), [])
            item.track_ids = tracks.get(item.option_id, [])
    return days, legs, activities, meals, stays


def build(trip, viewer=None, mine=False):
    """The trip's calendar as bytes."""
    days, legs, activities, meals, stays = load(trip)
    by_id = {day.pk: day for day in days}
    by_date = {day.date: day for day in days if day.date}
    me = Traveler.objects.filter(user=viewer).values_list("pk", flat=True).first() if (mine and viewer) else None

    def mine_ok(travelers):
        ids = {getattr(t, "pk", t) for t in travelers}
        return me is None or not ids or me in ids

    def day_travelers(day):
        return list(day.travelers.all()) if day else []

    def on(item, day, own=()):
        return mine_ok(on_it(own, item.track_ids, day_travelers(day)))

    trip_url = f"{settings.SITE_URL.rstrip('/')}{reverse('trips:trip_detail', args=[trip.pk])}"
    now = datetime.now(dt_timezone.utc)
    cal = calendar("Trip calendar", trip.name)
    cal.add("refresh-interval", REFRESH, parameters={"VALUE": "DURATION"})
    cal.add("x-published-ttl", "PT4H")  # Outlook's older name for REFRESH-INTERVAL

    def event(uid, summary, start, end, location="", lines=(), anchor=""):
        description = [line for line in lines if line] + [f"{trip_url}?item={anchor}#{anchor}" if anchor else trip_url]
        cal.add_component(vevent(uid, summary, start, end, location, "\n".join(description), now=now))

    for leg in legs:
        if not on(leg, by_date.get(leg.date)):
            continue
        icon = MODE_ICONS.get(leg.mode, "•")
        operator = " ".join(part for part in (leg.operator, leg.service_number) if part)
        lines = [operator, *_numbers(leg.cal_confirmations)]
        title = f"{icon} {leg.origin} → {leg.destination}"
        if leg.departure_at:
            end = leg.arrival_at or leg.departure_at + (leg.est_duration or timedelta(hours=1))
            event(f"leg-{leg.pk}", title, leg.departure_at.astimezone(dt_timezone.utc),
                  end.astimezone(dt_timezone.utc), leg.origin, lines, f"leg-{leg.pk}")
        elif leg.date:
            rough = f"Planned, no times yet{f' · {leg.est_duration_str}' if leg.est_duration else ''}"
            event(f"leg-{leg.pk}", f"{title} (planned)", leg.date, leg.date + timedelta(days=1), leg.origin,
                  [rough, *lines], f"leg-{leg.pk}")

    for activity in activities:
        day = by_id.get(activity.day_id)
        if day is None or not day.date or not on(activity, day, activity.travelers.all()):
            continue
        title = f"{ACTIVITY_ICONS.get(activity.kind, '•')} {activity.title}"
        place = activity.poi.name if activity.poi else activity.place_text
        lines = [activity.provider, *_numbers(activity.cal_confirmations)]
        if activity.start_time:
            start = datetime.combine(day.date, activity.start_time)  # naive = floating
            end = datetime.combine(day.date, activity.end_time) if activity.end_time else start + timedelta(hours=1)
            event(f"activity-{activity.pk}", title, start, end, place, lines, f"activity-{activity.pk}")
        else:
            event(f"activity-{activity.pk}", title, day.date, day.date + timedelta(days=1), place, lines,
                  f"activity-{activity.pk}")

    for meal in meals:
        day = by_id.get(meal.day_id)
        if day is None or not day.date or not on(meal, day):
            continue
        start = datetime.combine(day.date, meal.reserved_time)
        lines = [meal.cuisine, *_numbers(meal.cal_confirmations)]
        event(f"meal-{meal.pk}", f"🍽 {meal.get_meal_type_display()}: {meal.name}", start,
              start + timedelta(hours=1), "", lines, f"meal-{meal.pk}")

    # An undecided "choose one" is one all-day event naming its options (P4).
    for group in OptionGroup.objects.filter(trip=trip, state=OptionGroup.State.OPEN).prefetch_related("options"):
        day = by_id.get(group.day_id)
        if day is None or not day.date or not mine_ok(day_travelers(day)):
            continue
        titles = " / ".join(option.title for option in group.options.all()) or "no options yet"
        event(f"group-{group.pk}", f"🔀 Undecided: {titles}", day.date, day.date + timedelta(days=1), "",
              [group.prompt], f"group-{group.pk}")

    for stay in stays:
        if stay.check_out <= stay.check_in or not mine_ok(stay.track_ids):
            continue
        address = " ".join((stay.address or "").split())
        event(f"stay-{stay.pk}", f"🏨 {stay.name}", stay.check_in, stay.check_out, address or stay.name,
              _numbers(stay.cal_confirmations), f"stay-{stay.pk}")

    return cal.to_ical()
