"""Booking tasks and the items they're about (Phase E of
docs/plans/trip-items-and-confirmations.md).

Everything here works on rows the trip page already prefetched (``booking_tasks``,
``transport``, ``lodging``, ``days`` and the confirmations' ``confirmation_list`` set by
``views._attach_confirmations``), so the page pays no query for it:

- ``attach(trip)``: each leg and stay gets ``open_tasks``; each task gets ``item`` (its leg or
  stay), ``item_day`` and, when it has no item, ``suggestion`` — the one stay whose name its
  title contains, or the one leg whose two ends' first words it names ("ICE train seats
  Frankfurt→Augsburg" → Frankfurt Hof → Augsburg Hof). Two candidates means no suggestion.
- ``not_booked(trip)``: items that usually need booking (flights, rental cars, trains with an
  operator or service number, stays) with no confirmation and no task.
- ``first_confirmed(before, item_keys)``: which items just got their first confirmation, for
  the "mark these tasks done?" offer.
"""
import re


def _first_word(text):
    words = (text or "").split()
    return words[0] if words else ""


def _names(title, word):
    return bool(word) and re.search(r"(?<!\w)" + re.escape(word.lower()) + r"(?!\w)", title.lower()) is not None


def label(item):
    """How an item is named in a task's "For: …" line and the suggestion."""
    if hasattr(item, "check_in"):
        return item.name
    return f"{item.origin} → {item.destination}"


def suggest(task, legs, stays):
    """The one leg or stay this task's title names, or None."""
    dismissed = task.dismissed()
    title = task.title
    candidates = [stay for stay in stays
                  if len(stay.name.strip()) >= 4 and stay.name.strip().lower() in title.lower()]
    candidates += [leg for leg in legs
                   if _names(title, _first_word(leg.origin)) and _names(title, _first_word(leg.destination))
                   and _first_word(leg.origin).lower() != _first_word(leg.destination).lower()]
    candidates = [item for item in candidates if label(item).lower() not in dismissed]
    return candidates[0] if len(candidates) == 1 else None


def attach(trip, suggestions=False):
    legs = list(trip.transport.all())
    stays = list(trip.lodging.all())
    days_by_date = {day.date: day for day in trip.days.all() if day.date}
    leg_by_id = {leg.pk: leg for leg in legs}
    stay_by_id = {stay.pk: stay for stay in stays}
    for item in legs + stays:
        item.open_tasks = []
    for task in trip.booking_tasks.all():
        task.item = leg_by_id.get(task.leg_id) or stay_by_id.get(task.stay_id)
        task.item_day = None
        task.suggestion = None
        if task.item is not None:
            when = getattr(task.item, "date", None) if task.leg_id else task.item.check_in
            task.item_day = days_by_date.get(when)
            if not task.done:
                task.item.open_tasks.append(task)
        elif suggestions and not task.done:
            task.suggestion = suggest(task, legs, stays)


def _needs_booking(leg):
    Mode = type(leg).Mode
    return leg.mode in (Mode.PLANE, Mode.RENTAL_CAR) or (
        leg.mode == Mode.TRAIN and bool(leg.operator.strip() or leg.service_number.strip()))


def not_booked(trip):
    """[(item, kind_label)] with no confirmation and no task at all. Call after
    ``attach`` and ``views._attach_confirmations``."""
    tasked = {("leg", t.leg_id) for t in trip.booking_tasks.all() if t.leg_id} | \
             {("stay", t.stay_id) for t in trip.booking_tasks.all() if t.stay_id}
    found = []
    for leg in trip.transport.all():
        if _needs_booking(leg) and not getattr(leg, "confirmation_list", None) and ("leg", leg.pk) not in tasked:
            found.append((leg, leg.get_mode_display()))
    for stay in trip.lodging.all():
        if not getattr(stay, "confirmation_list", None) and ("stay", stay.pk) not in tasked:
            found.append((stay, "Stay"))
    return found


def confirmed_items(trip):
    """{("leg", pk), ("stay", pk)} covered by at least one of the trip's confirmations."""
    from .models import ConfirmationLink
    kinds = {"transportleg": "leg", "lodging": "stay"}
    rows = ConfirmationLink.objects.filter(confirmation__trip=trip, content_type__app_label="trips",
                                           content_type__model__in=kinds).values_list("content_type__model", "object_id")
    return {(kinds[model], pk) for model, pk in rows}


def offer_for(trip, before):
    """Open tasks on items that were unconfirmed in ``before`` (a ``confirmed_items`` set
    taken before the save) and are confirmed now."""
    newly = confirmed_items(trip) - before
    leg_ids = [pk for kind, pk in newly if kind == "leg"]
    stay_ids = [pk for kind, pk in newly if kind == "stay"]
    if not leg_ids and not stay_ids:
        return []
    from django.db.models import Q
    return list(trip.booking_tasks.filter(done=False).filter(Q(leg_id__in=leg_ids) | Q(stay_id__in=stay_ids)))
