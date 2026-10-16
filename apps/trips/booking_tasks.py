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


def kind_of(item):
    """leg / stay / activity: the task field and the URL kind for an item."""
    if hasattr(item, "check_in"):
        return "stay"
    if hasattr(item, "kind") and hasattr(item, "title"):
        return "activity"
    return "leg"


def anchor(item):
    """The item's id on the trip page."""
    return f"{kind_of(item)}-{item.pk}"


def describe(item):
    """Template-ready facts about an item: kind, label, anchor."""
    return {"kind": kind_of(item), "label": label(item), "anchor": anchor(item)}


def label(item):
    """How an item is named in a task's "For: …" line and the suggestion."""
    if hasattr(item, "check_in"):
        return item.name
    if hasattr(item, "title") and hasattr(item, "kind"):
        return item.title
    return f"{item.origin} → {item.destination}"


def suggest(task, legs, stays, activities=()):
    """The one leg, stay or activity this task's title names, or None."""
    dismissed = task.dismissed()
    title = task.title
    candidates = [stay for stay in stays
                  if len(stay.name.strip()) >= 4 and stay.name.strip().lower() in title.lower()]
    candidates += [activity for activity in activities
                   if len(activity.title.strip()) >= 4 and activity.title.strip().lower() in title.lower()]
    candidates += [leg for leg in legs
                   if _names(title, _first_word(leg.origin)) and _names(title, _first_word(leg.destination))
                   and _first_word(leg.origin).lower() != _first_word(leg.destination).lower()]
    candidates = [item for item in candidates if label(item).lower() not in dismissed]
    return candidates[0] if len(candidates) == 1 else None


def _activities(trip):
    """The days' prefetched activities (the trip page), else a query (other callers)."""
    days = list(trip.days.all())
    if days and all(hasattr(day, "ordered_activities") for day in days):
        return [activity for day in days for activity in day.ordered_activities]
    return list(trip.activities.select_related("day"))


def attach(trip, suggestions=False):
    legs = list(trip.transport.all())
    stays = list(trip.lodging.all())
    activities = _activities(trip)
    days_by_date = {day.date: day for day in trip.days.all() if day.date}
    leg_by_id = {leg.pk: leg for leg in legs}
    stay_by_id = {stay.pk: stay for stay in stays}
    activity_by_id = {activity.pk: activity for activity in activities}
    for item in legs + stays + activities:
        item.open_tasks = []
    for task in trip.booking_tasks.all():
        task.item = (leg_by_id.get(task.leg_id) or stay_by_id.get(task.stay_id)
                     or activity_by_id.get(task.activity_id))
        task.item_day = None
        task.suggestion = None
        if task.item is not None:
            if task.leg_id:
                when = task.item.date
            elif task.stay_id:
                when = task.item.check_in
            else:
                when = task.item.day.date
            task.item_day = days_by_date.get(when)
            if not task.done:
                task.item.open_tasks.append(task)
        elif suggestions and not task.done:
            task.suggestion = suggest(task, legs, stays, activities)
        task.item_info = describe(task.item) if task.item is not None else None
        task.suggestion_info = describe(task.suggestion) if task.suggestion is not None else None


def _needs_booking(leg):
    Mode = type(leg).Mode
    return leg.mode in (Mode.PLANE, Mode.RENTAL_CAR) or (
        leg.mode == Mode.TRAIN and bool(leg.operator.strip() or leg.service_number.strip()))


def not_booked(trip):
    """[{"item", "what", "when", "kind", "label", "anchor"}] with no confirmation and no task
    at all. Call after ``attach`` and ``views._attach_confirmations``."""
    tasked = {("leg", t.leg_id) for t in trip.booking_tasks.all() if t.leg_id} | \
             {("stay", t.stay_id) for t in trip.booking_tasks.all() if t.stay_id} | \
             {("activity", t.activity_id) for t in trip.booking_tasks.all() if t.activity_id}
    found = []
    for leg in trip.transport.all():
        if _needs_booking(leg) and not getattr(leg, "confirmation_list", None) and ("leg", leg.pk) not in tasked:
            found.append({"item": leg, "what": leg.get_mode_display(), "when": leg.date, **describe(leg)})
    for stay in trip.lodging.all():
        if not getattr(stay, "confirmation_list", None) and ("stay", stay.pk) not in tasked:
            found.append({"item": stay, "what": "Stay", "when": stay.check_in, **describe(stay)})
    for activity in _activities(trip):
        if (activity.kind in activity.BOOKABLE and not getattr(activity, "confirmation_list", None)
                and ("activity", activity.pk) not in tasked):
            found.append({"item": activity, "what": activity.get_kind_display(), "when": activity.day.date,
                          **describe(activity)})
    return found


def confirmed_items(trip):
    """{("leg", pk), ("stay", pk)} covered by at least one of the trip's confirmations."""
    from .models import ConfirmationLink
    kinds = {"transportleg": "leg", "lodging": "stay", "tripactivity": "activity"}
    rows = ConfirmationLink.objects.filter(confirmation__trip=trip, content_type__app_label="trips",
                                           content_type__model__in=kinds).values_list("content_type__model", "object_id")
    return {(kinds[model], pk) for model, pk in rows}


def offer_for(trip, before):
    """Open tasks on items that were unconfirmed in ``before`` (a ``confirmed_items`` set
    taken before the save) and are confirmed now."""
    newly = confirmed_items(trip) - before
    leg_ids = [pk for kind, pk in newly if kind == "leg"]
    stay_ids = [pk for kind, pk in newly if kind == "stay"]
    activity_ids = [pk for kind, pk in newly if kind == "activity"]
    if not leg_ids and not stay_ids and not activity_ids:
        return []
    from django.db.models import Q
    return list(trip.booking_tasks.filter(done=False).filter(
        Q(leg_id__in=leg_ids) | Q(stay_id__in=stay_ids) | Q(activity_id__in=activity_ids)))
