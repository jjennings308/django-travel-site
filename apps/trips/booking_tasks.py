"""Booking tasks and the items they're about (Phase E of
docs/plans/trip-items-and-confirmations.md).

Everything here works on rows the trip page already prefetched (``booking_tasks``,
``transport``, ``lodging``, ``days`` and the confirmations' ``confirmation_list`` set by
``views._attach_confirmations``), so the page pays no query for it:

A to-do covers any number of legs, stays and activities (booking-todos K1: ``TaskLink``, prefetched as
``booking_tasks__links``) — a round trip, a connection, a hotel and its transfer.

- ``attach(trip)``: each leg, stay and activity gets ``open_tasks`` (every to-do covering it); each task
  gets ``items`` (in date order), ``item`` (the first), ``item_day``, ``item_info``, ``cover_label``
  ("Augsburg → Munich and back", "PIT → ATL → FRA", "Hotel Laimer Hof + 1 more") and ``more_labels``,
  and, when it covers nothing, ``suggestion`` — the one stay whose name its title contains, or the one
  leg whose two ends' first words it names ("ICE train seats Frankfurt→Augsburg" → Frankfurt Hof →
  Augsburg Hof). Two candidates means no suggestion.
- ``partners(item, legs)``: a leg's way back and the legs it connects with on the day — offered as
  pre-ticked boxes when a to-do is added from that leg, never linked on their own.
- ``not_booked(trip)``: items that usually need booking (flights, rental cars, trains with an
  operator or service number, stays) with no confirmation and no task.
- ``offer_for(trip, before)``: the "mark these tasks done?" offer, for to-dos all of whose items are
  confirmed now and one of which just was.
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


def _when(item):
    """Sort key: an item's date, then (legs) its departure or order."""
    from datetime import date as _date
    if kind_of(item) == "stay":
        return (item.check_in or _date.max, 1, 0, item.pk)
    if kind_of(item) == "activity":
        return (item.day.date if item.day_id and item.day.date else _date.max, 2,
                item.start_time.hour * 60 + item.start_time.minute if item.start_time else 0, item.pk)
    return (item.date or _date.max, 0, item.departure_at.timestamp() if item.departure_at else item.order, item.pk)


def _same_place(city_a, text_a, city_b, text_b):
    """Two leg ends are one place: the same catalogue city when both have one, else the same first word."""
    if city_a and city_b:
        return city_a == city_b
    word_a, word_b = _first_word(text_a).lower(), _first_word(text_b).lower()
    return bool(word_a) and word_a == word_b


def _reverses(leg, other):
    """``other`` goes back the way ``leg`` came (its ends swapped)."""
    return (_same_place(other.origin_city_id, other.origin, leg.destination_city_id, leg.destination)
            and _same_place(other.destination_city_id, other.destination, leg.origin_city_id, leg.origin))


def _connects(first, second):
    """``second`` leaves from where ``first`` arrives."""
    return _same_place(first.destination_city_id, first.destination, second.origin_city_id, second.origin)


def _later(other, leg):
    """``other`` is after ``leg``: a later date, or the same date and later (times, else order)."""
    if other.date != leg.date:
        return bool(other.date and leg.date and other.date > leg.date)
    if other.departure_at and leg.departure_at:
        return other.departure_at > leg.departure_at
    return (other.order, other.pk) > (leg.order, leg.pk)


def chain(leg, legs):
    """The legs connected to ``leg`` on its date (each one's destination the next one's origin), in order,
    ``leg`` included."""
    same_day = sorted((other for other in legs if other.date == leg.date), key=_when)
    run = [leg]
    while True:  # backwards
        before = [o for o in same_day if o not in run and _connects(o, run[0]) and _later(run[0], o)]
        if not before:
            break
        run.insert(0, before[-1])
    while True:  # forwards
        after = [o for o in same_day if o not in run and _connects(run[-1], o) and _later(o, run[-1])]
        if not after:
            break
        run.append(after[0])
    return run


def partners(item, legs):
    """[(leg, why)] a to-do about ``item`` probably covers too: a leg's way back (the first later leg with
    its ends swapped: "the way back") and the legs it connects with that day ("connection"). Nothing for
    stays and activities. Pure; used to pre-tick boxes, never to link on its own."""
    if kind_of(item) != "leg":
        return []
    found = []
    for other in chain(item, legs):
        if other is not item and other.pk != item.pk and not _reverses(item, other):
            found.append((other, "connection"))
    back = sorted((o for o in legs if o.pk != item.pk and _reverses(item, o) and _later(o, item)), key=_when)
    if back:
        found.append((back[0], "the way back"))
    return found


def cover_label(items):
    """How a to-do's items read together: "Augsburg → Munich and back" (a leg and its reverse), "PIT → ATL →
    FRA" (legs chained on one date), one item's label, else "Hotel Laimer Hof + 1 more"."""
    if not items:
        return ""
    if len(items) == 1:
        return label(items[0])
    if all(kind_of(item) == "leg" for item in items):
        if len(items) == 2 and _reverses(items[0], items[1]):
            return f"{items[0].origin} → {items[0].destination} and back"
        if (len({leg.date for leg in items}) == 1
                and all(_connects(a, b) for a, b in zip(items, items[1:]))):
            return " → ".join([items[0].origin] + [leg.destination for leg in items])
    return f"{label(items[0])} + {len(items) - 1} more"


def _item_index(legs, stays, activities):
    """{(content type id, pk): item} for the trip's legs, stays and activities."""
    from django.contrib.contenttypes.models import ContentType
    from .models import Lodging, TransportLeg, TripActivity
    types = ContentType.objects.get_for_models(TransportLeg, Lodging, TripActivity)
    index = {}
    for model, rows in ((TransportLeg, legs), (Lodging, stays), (TripActivity, activities)):
        for row in rows:
            index[(types[model].pk, row.pk)] = row
    return index


def attach(trip, suggestions=False):
    legs = list(trip.transport.all())
    stays = list(trip.lodging.all())
    activities = _activities(trip)
    days_by_date = {day.date: day for day in trip.days.all() if day.date}
    index = _item_index(legs, stays, activities)
    for item in legs + stays + activities:
        item.open_tasks = []
    for task in trip.booking_tasks.all():
        items = [index[(link.content_type_id, link.object_id)] for link in task.links.all()
                 if (link.content_type_id, link.object_id) in index]
        task.items = sorted(items, key=_when)
        task.item = task.items[0] if task.items else None
        task.cover_label = cover_label(task.items)
        task.more_labels = ", ".join(label(item) for item in task.items[1:])
        task.item_day = None
        task.suggestion = None
        if task.item is not None:
            kind = kind_of(task.item)
            when = (task.item.date if kind == "leg" else task.item.check_in if kind == "stay"
                    else task.item.day.date)
            task.item_day = days_by_date.get(when)
            if not task.done:
                for item in task.items:
                    item.open_tasks.append(task)
        elif suggestions and not task.done:
            task.suggestion = suggest(task, legs, stays, activities)
        task.item_info = describe(task.item) if task.item is not None else None
        task.suggestion_info = describe(task.suggestion) if task.suggestion is not None else None


def _tasked(trip):
    """{("leg" / "stay" / "activity", pk)} that any to-do covers, from the prefetched links."""
    from django.contrib.contenttypes.models import ContentType
    from .models import Lodging, TransportLeg, TripActivity
    types = ContentType.objects.get_for_models(TransportLeg, Lodging, TripActivity)
    kinds = {types[TransportLeg].pk: "leg", types[Lodging].pk: "stay", types[TripActivity].pk: "activity"}
    return {(kinds[link.content_type_id], link.object_id) for task in trip.booking_tasks.all()
            for link in task.links.all() if link.content_type_id in kinds}


def _needs_booking(leg):
    Mode = type(leg).Mode
    return leg.mode in (Mode.PLANE, Mode.RENTAL_CAR) or (
        leg.mode == Mode.TRAIN and bool(leg.operator.strip() or leg.service_number.strip()))


def not_booked(trip):
    """[{"item", "what", "when", "kind", "label", "anchor"}] with no confirmation and no task
    at all. Call after ``attach`` and ``views._attach_confirmations``."""
    tasked = _tasked(trip)
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


def task_keys(task):
    """{("leg" / "stay" / "activity", pk)} a to-do covers (one query)."""
    kinds = {"transportleg": "leg", "lodging": "stay", "tripactivity": "activity"}
    return {(kinds[model], pk) for model, pk in task.links.values_list("content_type__model", "object_id")
            if model in kinds}


def offer_after(trip, newly):
    """Open to-dos covering one of ``newly`` (item keys just confirmed) all of whose items are confirmed now."""
    if not newly:
        return []
    confirmed = confirmed_items(trip)
    found = []
    for task in trip.booking_tasks.filter(done=False, links__isnull=False).distinct():
        keys = task_keys(task)
        if keys & newly and keys <= confirmed:
            found.append(task)
    return found


def offer_for(trip, before):
    """The "mark these done?" offer after a save: open to-dos covering an item that was unconfirmed in
    ``before`` (a ``confirmed_items`` set taken before the save) and all of whose items are confirmed now."""
    return offer_after(trip, confirmed_items(trip) - before)
