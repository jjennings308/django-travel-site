"""Move the whole trip to new dates (docs/plans/shift-and-reorder-days.md, DR1).

Every day, journey and stay carries its own date, so moving a trip by N days means moving each of them:

- ``shift_plan(trip, n)`` — the preview, nothing saved. Works over the trip page's prefetch
  (``views._trip_page_queryset`` with ``views._attach_confirmations`` and ``trip_notes.attach``, but *not*
  ``options.attach``: undecided choices' items move too). Lists the days, journeys (local wall-clock times kept),
  stays and to-do due dates as old → new, and the warnings: booked items (moved here, never at the provider),
  items linked to an event whose dates the new day falls outside, catalogue notes' closed weekdays newly hit, and
  journeys on a date that is no day of the trip.
- ``shift(trip, n, user, …)`` — applies it in one transaction under one history line ("Moved the trip 7 days
  earlier: Sep 17–29 → Sep 10–22"), whose ``before`` holds every old value, plus the booking to-dos it made.
  Payments, ``booked_on`` and catalogue events never move; due dates only when asked. The per-leg "time change"
  notices are held back; one "the trip has moved" notice goes out instead when a journey now leaves within
  ``changes.URGENT_DAYS``.
- ``undo_shift(change)`` — puts every value back (only while that line is the trip's newest change) and deletes
  the booking to-dos it made unless they've been edited or done since.

``move_trip=False`` moves the contents only: the fit-the-days page's offer after Settings already saved a new start
date (``trips:trip_shift?moved_from=…``).

Putting days in a new order (DR2) keeps the trip's dates where they are and moves the days between them:
``reorder_plan(trip, order, days)`` (``order`` = every day's pk once, in the new order; the n-th day gets the n-th of
the days' dates) and ``reorder(trip, order, user, …)``. A day's contents ride along on its row; its journeys get its
new date (wall clock kept); a stay moves with its nights only when they stay together and in order, otherwise it
stays and is listed. Then the days are numbered again by date (``day_fit.renumber``). Warnings as for a shift plus
text naming a day that is now another day's number (Tidy's ``day_slip``). One history line, undone by
``undo_move`` like a shift.
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import BookingTask, Day, Lodging, TaskLink, TransportLeg, TripChange, format_local_time, get_timezone

UTC = dt_timezone.utc
WEEKDAYS = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]


class CannotMove(Exception):
    """Why a move or its undo was refused (shown to the editor)."""


def _d(value):
    return f"{value:%b} {value.day}" if value else "no date"


def span(start, end):
    """"Sep 17–29", "Sep 28–Oct 3", "Dec 30, 2026–Jan 2, 2027"."""
    if not start or not end:
        return _d(start or end)
    if start.year != end.year:
        return f"{_d(start)}, {start.year}–{_d(end)}, {end.year}"
    if start.month == end.month:
        return f"{_d(start)}–{end.day}"
    return f"{_d(start)}–{_d(end)}"


def wall_clock_plus(value, zone_name, n):
    """``value`` (UTC) moved ``n`` days on the wall clock of ``zone_name``: a 10:15 train stays 10:15, so a
    summer-time change between the two dates is right. UTC when the zone is unknown."""
    if value is None:
        return None
    zone = get_timezone(zone_name) or UTC
    local = value.astimezone(zone).replace(tzinfo=None) + timedelta(days=n)
    return local.replace(tzinfo=zone).astimezone(UTC)


def _local(value, zone_name):
    zone = get_timezone(zone_name) or UTC
    return value.astimezone(zone)


def describe(n):
    days = abs(n)
    unit = "day" if days == 1 else "days"
    return f"{days} {unit} {'later' if n > 0 else 'earlier'}"


def _label(item):
    from .booking_tasks import label
    name = type(item).__name__
    if name == "Meal":
        return item.name
    if name == "Section":
        return item.title or "a note"
    return label(item)


# ------------------------------------------------------------------------------------------------ preview

def shift_plan(trip, n, move_trip=True):
    """What moving the trip by ``n`` days would do (nothing saved). See the module docstring."""
    days = sorted(trip.days.all(), key=lambda d: (d.date is None, d.date or date.min, d.day_number))
    day_dates = {day.date for day in days if day.date}
    plus = lambda value: value + timedelta(days=n) if value else value  # noqa: E731

    legs = []
    for leg in sorted(trip.transport.all(), key=lambda l: (l.date or date.min, l.departure_at or datetime.min.replace(tzinfo=UTC), l.pk)):
        new_departure = wall_clock_plus(leg.departure_at, leg.origin_timezone, n)
        new_date = _local(new_departure, leg.origin_timezone).date() if new_departure else plus(leg.date)
        legs.append({"leg": leg, "label": _label(leg), "old": leg.date, "new": new_date,
                     "time": format_local_time(new_departure, leg.origin_timezone) if new_departure else "",
                     "stray": bool(leg.date) and leg.date not in day_dates})
    stays = [{"stay": stay, "label": stay.name, "old": (stay.check_in, stay.check_out),
              "new": (plus(stay.check_in), plus(stay.check_out))}
             for stay in sorted(trip.lodging.all(), key=lambda s: (s.check_in or date.min, s.pk))]
    tasks = [{"task": task, "old": task.due, "new": plus(task.due)}
             for task in sorted((t for t in trip.booking_tasks.all() if t.due), key=lambda t: (t.due, t.pk))]

    # Booked items: every confirmation linked to something that moves.
    booked = []
    for confirmation in sorted(trip.confirmations.all(), key=lambda c: c.confirmation_number.lower()):
        items = getattr(confirmation, "_items", None) or []
        if not items:
            continue
        dates = [d for item in items for d in _item_dates(item) if d]
        booked.append({"confirmation": confirmation, "items": [_label(i) for i in items],
                       "was": span(min(dates), max(dates)) if dates else "",
                       "now": span(plus(min(dates)), plus(max(dates))) if dates else ""})

    events, closed = [], []
    for day in days:
        if not day.date:
            continue
        new = day.date + timedelta(days=n)
        number = day.day_number
        for item in [*getattr(day, "ordered_activities", []), *getattr(day, "ordered_sections", [])]:
            event = getattr(item, "event", None) if getattr(item, "event_id", None) else None
            if event is not None and event.start_date:
                last = event.end_date or event.start_date
                if not event.start_date <= new <= last:
                    what = _label(item)
                    lead = (f"{event.name} runs {span(event.start_date, last)}" if what == event.name
                            else f"{what} is linked to {event.name}, {span(event.start_date, last)}")
                    events.append(f"{lead}; Day {number} will be {_d(new)}")
        for item in [*getattr(day, "ordered_meals", []), *getattr(day, "ordered_activities", []),
                     *getattr(day, "ordered_sections", [])]:
            for note in getattr(item, "trip_notes", []):
                shut = note.closed_weekdays or []
                if new.weekday() in shut and day.date.weekday() not in shut:
                    who, what = note.from_name or _label(item), _label(item)
                    closed.append(f"{who} is closed on {WEEKDAYS[new.weekday()]}"
                                  + (f" ({what})" if what != who else "") + f"; Day {number} will be a {new:%A}")
                    break

    soon = timezone.localdate() + timedelta(days=_urgent_days())
    return {
        "n": n, "describe": describe(n), "move_trip": move_trip,
        "old_range": (trip.start_date, trip.end_date),
        "new_range": (plus(trip.start_date), plus(trip.end_date)) if move_trip else (trip.start_date, trip.end_date),
        "old_span": span(trip.start_date, trip.end_date),
        "new_span": span(plus(trip.start_date), plus(trip.end_date)) if move_trip else span(trip.start_date, trip.end_date),
        "days": [{"day": day, "old": day.date, "new": plus(day.date)} for day in days],
        "legs": legs, "stays": stays, "tasks": tasks, "booked": booked, "events": events, "closed": closed,
        "strays": [row for row in legs if row["stray"]],
        "urgent": any(row["new"] and timezone.localdate() <= row["new"] <= soon for row in legs),
    }


def _item_dates(item):
    name = type(item).__name__
    if name == "TransportLeg":
        return [item.date]
    if name == "Lodging":
        return [item.check_in, item.check_out]
    day = getattr(item, "day", None)
    return [day.date] if day is not None else []


def _urgent_days():
    from .changes import URGENT_DAYS
    return URGENT_DAYS


# ------------------------------------------------------------------------------------------------- apply

def shift(trip, n, user=None, move_due=False, booking_todos=True, move_trip=True):
    """Move the trip by ``n`` days (see the module docstring). Returns {"change", "made", "urgent"}."""
    from . import changes
    if not n:
        raise CannotMove("The new dates are the same as the old ones.")
    days = list(Day.objects.filter(trip=trip))
    legs = list(TransportLeg.objects.filter(trip=trip))
    stays = list(Lodging.objects.filter(trip=trip))
    tasks = list(BookingTask.objects.filter(trip=trip, due__isnull=False)) if move_due else []
    before = {
        "shift": n, "move_trip": move_trip,
        "trip": [_iso(trip.start_date), _iso(trip.end_date)],
        "days": {str(day.pk): _iso(day.date) for day in days},
        "legs": {str(leg.pk): [_iso(leg.date), _iso(leg.departure_at), _iso(leg.arrival_at)] for leg in legs},
        "stays": {str(stay.pk): [_iso(stay.check_in), _iso(stay.check_out)] for stay in stays},
        "tasks": {str(task.pk): _iso(task.due) for task in tasks},
        "made_tasks": {},
    }
    plus = lambda value: value + timedelta(days=n) if value else value  # noqa: E731
    old_span = span(trip.start_date, trip.end_date)
    new_span = span(plus(trip.start_date), plus(trip.end_date)) if move_trip else old_span
    if move_trip:
        summary = f"Moved the trip {describe(n)}: {old_span} → {new_span}"
    else:
        summary = f"Moved the days, journeys and stays {describe(n)} to fit the new dates ({new_span})"
    soon_last = timezone.localdate() + timedelta(days=_urgent_days())
    urgent = False
    with transaction.atomic(), changes.batch(summary, trip=trip, actor=user, item=trip, no_urgent=True) as state:
        # Days first, so a journey placed in a day's travel section still fits it after moving.
        for day in days:
            if day.date:
                day.date = plus(day.date)
                day.save(update_fields=["date"])
        for leg in legs:
            if leg.departure_at:
                leg.departure_at = wall_clock_plus(leg.departure_at, leg.origin_timezone, n)
                leg.arrival_at = wall_clock_plus(leg.arrival_at, leg.destination_timezone, n)
            else:
                leg.date = plus(leg.date)
            leg.save()  # the date follows the local departure
            if leg.date and timezone.localdate() <= leg.date <= soon_last:
                urgent = True
        for stay in stays:
            stay.check_in, stay.check_out = plus(stay.check_in), plus(stay.check_out)
            stay.save()
        if move_trip:
            trip.start_date, trip.end_date = plus(trip.start_date), plus(trip.end_date)
            trip.save(update_fields=["start_date", "end_date"])
        for task in tasks:
            task.due = plus(task.due)
            task.save(update_fields=["due"])
        made = _booking_todos(trip, f"The trip moved to {new_span} on this site; the booking itself hasn't changed.") \
            if booking_todos else []
        before["made_tasks"] = {str(task.pk): _task_print(task) for task in made}
        state["before"] = before
    if urgent:
        _notice_moved(trip, user, new_span)
    return {"change": state["line"], "made": made, "urgent": urgent}


def _booking_todos(trip, notes, only=None):
    """One to-do per booking linked to something that moved: "Change booking GCH7JS to the new dates", covering
    its journeys, stays and activities (High). ``only``: the confirmation pks to do (default all with links)."""
    from .models import Confirmation, TASKABLE
    taskable = tuple(TASKABLE.values())
    made = []
    for confirmation in Confirmation.objects.filter(trip=trip).prefetch_related("links__content_type"):
        if only is not None and confirmation.pk not in only:
            continue
        items = [link.item for link in confirmation.links.all() if link.item is not None]
        if not items:
            continue
        task = BookingTask.objects.create(
            trip=trip, title=f"Change booking {confirmation.confirmation_number} to the new dates",
            priority=BookingTask.Priority.HIGH, notes=notes)
        for item in items:
            if isinstance(item, taskable):
                TaskLink.link(task, item)
        made.append(task)
    return made


def _task_print(task):
    """What a made to-do looked like, so Undo can tell whether anyone has touched it since."""
    return {"title": task.title, "notes": task.notes, "done": task.done, "priority": task.priority,
            "due": _iso(task.due)}


def _notice_moved(trip, user, new_span):
    """One notice instead of one per leg: the trip moved and something now leaves within a week."""
    from . import changes

    def send():
        from apps.notifications.services import notify
        url = reverse("trips:trip_detail", args=[trip.pk])
        for person in changes.recipients(trip, exclude_user_id=getattr(user, "pk", None)):
            notify(person, "trip_changed", f"“{trip.name}” has moved",
                   f"“{trip.name}” now runs {new_span}. Check the times of the journeys this week.", url, obj=trip)

    transaction.on_commit(send)


def _iso(value):
    return value.isoformat() if value else None


def _date_of(value):
    return date.fromisoformat(value) if value else None


def _datetime_of(value):
    return datetime.fromisoformat(value) if value else None


# ------------------------------------------------------------------------------------------------- undo

def is_move(change):
    """A whole-trip move (DR1) or a new order of days (DR2): undone by ``undo_move``."""
    return bool(change.before) and ("shift" in change.before or "reorder" in change.before)


def undo_move(change, user=None):
    """Put back what ``shift`` or ``reorder`` moved. Returns the to-dos kept (edited or done since)."""
    from . import changes, day_fit
    from .models import Trip
    before = change.before or {}
    if not is_move(change):
        raise CannotMove("That isn't a move of the trip.")
    trip = Trip.objects.filter(pk=change.trip_id, deleted_at=None).first()
    if trip is None:
        raise CannotMove("The trip is gone.")
    if changes.latest_change_ids(trip).get("newest") != change.pk:
        raise CannotMove("The trip has changed since; only the newest change can be undone.")
    kept = []
    summary = f"Undid “{change.summary}”"
    with transaction.atomic(), changes.batch(summary[:450], trip=trip, actor=user, no_urgent=True):
        numbers = {}
        for day in Day.objects.filter(trip=trip, pk__in=[int(pk) for pk in before["days"]]):
            value = before["days"][str(day.pk)]
            if isinstance(value, list):  # a reorder: [date, day number]
                value, numbers[day.pk] = value
            day.date = _date_of(value)
            day.save(update_fields=["date"])
        if numbers:
            day_fit.renumber(trip)  # by date, which puts the old numbers back
        for leg in TransportLeg.objects.filter(trip=trip, pk__in=[int(pk) for pk in before["legs"]]):
            old_date, departure, arrival = before["legs"][str(leg.pk)]
            leg.date, leg.departure_at, leg.arrival_at = _date_of(old_date), _datetime_of(departure), _datetime_of(arrival)
            leg.save()
        for stay in Lodging.objects.filter(trip=trip, pk__in=[int(pk) for pk in before["stays"]]):
            stay.check_in, stay.check_out = (_date_of(v) for v in before["stays"][str(stay.pk)])
            stay.save()
        if before.get("move_trip"):
            trip.start_date, trip.end_date = (_date_of(v) for v in before["trip"])
            trip.save(update_fields=["start_date", "end_date"])
        for task in BookingTask.objects.filter(trip=trip, pk__in=[int(pk) for pk in before.get("tasks", {})]):
            task.due = _date_of(before["tasks"][str(task.pk)])
            task.save(update_fields=["due"])
        for task in BookingTask.objects.filter(trip=trip, pk__in=[int(pk) for pk in before.get("made_tasks", {})]):
            if _task_print(task) == before["made_tasks"][str(task.pk)]:
                task.delete()
            else:
                kept.append(task)
    return kept


undo_shift = undo_move  # DR1's name


# ------------------------------------------------------------------------------------------------ reorder (DR2)

def _check_order(trip, days, order):
    """The days in ``order`` (each once, all of them), or CannotMove."""
    by_pk = {day.pk: day for day in days}
    if sorted(order) != sorted(by_pk):
        raise CannotMove("Every day must be in the new order once.")
    dated = [day.date for day in days if day.date]
    if len(dated) != len(days) or len(set(dated)) != len(dated):
        raise CannotMove("Every day needs its own date first: fit the days to the trip's dates.")
    if trip.start_date and trip.end_date and (len(days) != (trip.end_date - trip.start_date).days + 1
                                              or min(dated) != trip.start_date):
        raise CannotMove("The days don't match the trip's dates: fit the days first.")
    return [by_pk[pk] for pk in order]


def _day_name(number, day):
    return f"Day {number}" + (f" {day.city.name}" if day.city_id and day.city else (f" — {day.theme}" if day.theme else ""))


def reorder_plan(trip, order, days=None):
    """What putting the days in ``order`` would do (nothing saved). ``days``: the trip page's days (from
    ``views._trip_page_context``) for the event and closed-day warnings; the moves themselves come from the
    database, so undecided choices' journeys move too."""
    from .models import Confirmation
    from .tidy import _day_slips
    from .tidying import snapshot
    all_days = list(Day.objects.filter(trip=trip).select_related("city"))
    ordered = _check_order(trip, all_days, [int(pk) for pk in order])
    slots = sorted(day.date for day in all_days)
    new = {day.pk: slots[i] for i, day in enumerate(ordered)}
    number = {day.pk: i + 1 for i, day in enumerate(ordered)}
    by_date = {day.date: day for day in all_days}
    old_date = {day.pk: day.date for day in all_days}
    moved = {pk for pk, when in new.items() if when != old_date[pk]}

    legs = []
    for leg in TransportLeg.objects.filter(trip=trip):
        day = by_date.get(leg.date)
        if day is None or day.pk not in moved:
            continue
        n = (new[day.pk] - day.date).days
        departure = wall_clock_plus(leg.departure_at, leg.origin_timezone, n)
        legs.append({"leg": leg, "label": _label(leg), "n": n, "old": leg.date, "new": new[day.pk],
                     "time": format_local_time(departure, leg.origin_timezone) if departure else ""})

    stays, kept_stays = [], []
    for stay in Lodging.objects.filter(trip=trip):
        if not stay.check_in or not stay.check_out or stay.check_out <= stay.check_in:
            continue
        nights = (stay.check_out - stay.check_in).days
        night_days = [by_date.get(stay.check_in + timedelta(days=k)) for k in range(nights)]
        if not any(day is not None and day.pk in moved for day in night_days):
            continue
        together = all(day is not None for day in night_days) and all(
            (new[b.pk] - new[a.pk]).days == 1 for a, b in zip(night_days, night_days[1:]))
        if together:
            check_in = new[night_days[0].pk]
            stays.append({"stay": stay, "label": stay.name, "old": (stay.check_in, stay.check_out),
                          "new": (check_in, check_in + timedelta(days=nights))})
        else:
            covers = sorted((d for d in all_days if stay.check_in <= new[d.pk] < stay.check_out),
                            key=lambda d: new[d.pk])
            names = [_day_name(number[d.pk], d) for d in covers]
            listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
            kept_stays.append(f"{stay.name} ({span(stay.check_in, stay.check_out)}) now covers {listed}: check it")

    moved_legs = {row["leg"].pk for row in legs}
    moved_stays = {row["stay"].pk for row in stays}

    def item_moved(item):
        name = type(item).__name__
        if name == "TransportLeg":
            return item.pk in moved_legs
        if name == "Lodging":
            return item.pk in moved_stays
        return getattr(item, "day_id", None) in moved

    booked = []
    for confirmation in Confirmation.objects.filter(trip=trip).prefetch_related("links__content_type"):
        items = [link.item for link in confirmation.links.all() if link.item is not None]
        if any(item_moved(item) for item in items):
            booked.append({"confirmation": confirmation, "items": [_label(i) for i in items if item_moved(i)]})

    events, closed = [], []
    for day in days or []:
        if day.pk not in moved:
            continue
        when, num = new[day.pk], number[day.pk]
        for item in [*getattr(day, "ordered_activities", []), *getattr(day, "ordered_sections", [])]:
            event = getattr(item, "event", None) if getattr(item, "event_id", None) else None
            if event is not None and event.start_date:
                last = event.end_date or event.start_date
                if not event.start_date <= when <= last:
                    what = _label(item)
                    lead = (f"{event.name} runs {span(event.start_date, last)}" if what == event.name
                            else f"{what} is linked to {event.name}, {span(event.start_date, last)}")
                    events.append(f"{lead}; it would be on Day {num}, {_d(when)}")
        for item in [*getattr(day, "ordered_meals", []), *getattr(day, "ordered_activities", []),
                     *getattr(day, "ordered_sections", [])]:
            for note in getattr(item, "trip_notes", []):
                shut = note.closed_weekdays or []
                if when.weekday() in shut and day.date.weekday() not in shut:
                    who, what = note.from_name or _label(item), _label(item)
                    closed.append(f"{who} is closed on {WEEKDAYS[when.weekday()]}"
                                  + (f" ({what})" if what != who else "") + f"; Day {num} would be a {when:%A}")
                    break

    # Text that names a day ("see Day 3") now on a day with another number: Tidy's day_slip rule, new ones only.
    slips = []
    snap = snapshot(trip)
    for plain in snap["days"]:
        if plain["id"] not in number:
            continue
        old_keys = {s.key for section in plain["sections"] for s in _day_slips(plain, section)}
        renumbered = dict(plain, number=number[plain["id"]])
        for section in plain["sections"]:
            for slip in _day_slips(renumbered, section):
                if slip.key not in old_keys:
                    slips.append(f"{slip.where} on Day {renumbered['number']} says “{_slip_ref(slip.before)}”: "
                                 f"“{slip.before[:80]}”")

    rows = [{"pk": day.pk, "old": day.date, "new": new[day.pk], "number": number[day.pk],
             "moved": day.pk in moved} for day in ordered]
    return {"rows": rows, "slots": slots, "moved": moved, "legs": legs, "stays": stays, "kept_stays": kept_stays,
            "booked": booked, "events": events, "closed": closed, "slips": slips,
            "summary": "Reordered days: " + ", ".join(
                f"{_d(new[d.pk])} {d.city.name if d.city_id and d.city else (d.theme or f'Day {d.day_number}')}"
                for d in ordered if d.pk in moved)}


def _slip_ref(text):
    from .tidy import DAY_REF
    found = DAY_REF.search(text)
    return found.group(0) if found else "Day …"


def reorder(trip, order, user=None, booking_todos=True):
    """Put the days in ``order`` (see the module docstring). Returns {"change", "made", "plan"}."""
    from . import changes, day_fit
    plan = reorder_plan(trip, order)
    if not plan["moved"]:
        raise CannotMove("That's the order they're in already.")
    days = list(Day.objects.filter(trip=trip))
    legs = {row["leg"].pk: row for row in plan["legs"]}
    stays = {row["stay"].pk: row for row in plan["stays"]}
    new = {row["pk"]: row["new"] for row in plan["rows"]}
    before = {
        "reorder": True,
        "days": {str(day.pk): [_iso(day.date), day.day_number] for day in days},
        "legs": {str(row["leg"].pk): [_iso(row["leg"].date), _iso(row["leg"].departure_at), _iso(row["leg"].arrival_at)]
                 for row in plan["legs"]},
        "stays": {str(row["stay"].pk): [_iso(row["stay"].check_in), _iso(row["stay"].check_out)] for row in plan["stays"]},
        "made_tasks": {},
    }
    summary = plan["summary"] if len(plan["summary"]) <= 400 else plan["summary"][:397] + "…"
    with transaction.atomic(), changes.batch(summary, trip=trip, actor=user, item=trip, no_urgent=True) as state:
        for day in days:
            if new[day.pk] != day.date:
                day.date = new[day.pk]
                day.save(update_fields=["date"])
        for leg in TransportLeg.objects.filter(pk__in=legs):
            n = legs[leg.pk]["n"]
            if leg.departure_at:
                leg.departure_at = wall_clock_plus(leg.departure_at, leg.origin_timezone, n)
                leg.arrival_at = wall_clock_plus(leg.arrival_at, leg.destination_timezone, n)
            else:
                leg.date = legs[leg.pk]["new"]
            leg.save()
        for stay in Lodging.objects.filter(pk__in=stays):
            stay.check_in, stay.check_out = stays[stay.pk]["new"]
            stay.save()
        day_fit.renumber(trip)
        made = _booking_todos(trip, "The days were put in a new order on this site; the booking itself hasn't changed.",
                              only={row["confirmation"].pk for row in plan["booked"]}) if booking_todos else []
        before["made_tasks"] = {str(task.pk): _task_print(task) for task in made}
        state["before"] = before
    return {"change": state["line"], "made": made, "plan": plan}
