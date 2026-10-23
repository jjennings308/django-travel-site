"""The day-by-day assembly both outputs need: the web trip page (``views.trip_detail``) and the
PDF booklet (``pdf.py``). Pure functions over the rows ``views._trip_page_queryset`` prefetched,
no queries; each sets attributes the templates read. (docs/plans/trip-page-ux.md, U1.)

- ``place_legs(trip)``: each leg on its day — ``day.day_legs`` (all of that date, in order),
  ``section.placed_legs`` (the travel section it's placed in), ``day.auto_legs`` (the rest),
  ``day.has_travel``, ``day.travel_total`` and ``leg.on_day``; returns the legs whose date is no
  day of the trip.
- ``travel_total(legs)``: "2 legs · ~3 h 15 min" when every leg has a time or an estimate.
- ``attach_stays(days, stays)``: where you sleep each night — ``day.stay`` (check-in ≤ date <
  check-out), ``day.checking_in`` / ``day.checking_out`` (stays starting / ending that day); returns
  the stays whose check-in is no day of the trip.
- ``overview(days, not_booked, tasks)``: the web page's Overview row and day summary (U2) —
  ``day.overnight``, ``day.travel_icons``, ``day.travel_summary``, ``day.highlights``,
  ``day.attention``. Run after ``place_legs`` and ``attach_stays``.
- ``open_day(days, today)``: which day the page opens on — today's during the trip, Day 1 before
  it, none after it.
- ``attach_links(trip, days)``: contacts and info notes linked to items (U4) — each item's
  ``refs``, each day's ``good_to_know`` (linked to the day or one of its sections) and each
  contact/note's ``on`` (where it's linked: label, anchor, day). Run after ``place_legs``.
- ``anchor(item)``: the trip page id of an item's row or card, else of its day.
- ``timeline(days)``: each day's ``day.timeline`` (legs, activities and reserved meals in local
  time order), ``day.any_time`` (untimed legs in their order, then untimed activities) and
  ``day.food_ideas`` (meals with no reservation time) (U3). Run after ``place_legs``.
"""
from .models import Contact, Day, Lodging, Meal, Section, TransportLeg, TripActivity, item_label


def travel_total(legs):
    """ "2 legs · ~3 h 15 min" (the "~" when any leg is only planned), or "" when a leg has
    neither a time nor an estimate."""
    times = [leg.travel_time for leg in legs]
    if not legs or not all(times):
        return ""
    minutes = int(sum(t.total_seconds() for t in times) // 60)
    hours, minutes = divmod(minutes, 60)
    span = f"{hours} h {minutes} min" if hours and minutes else f"{hours} h" if hours else f"{minutes} min"
    approx = "~" if any(leg.is_planned for leg in legs) else ""
    count = len(legs)
    return f"{count} leg{'' if count == 1 else 's'} · {approx}{span}"


def place_legs(trip):
    """Put each leg on its day (see the module docstring). Returns the stray legs."""
    legs = list(trip.transport.all())  # Meta order: date, time, order
    days = list(trip.days.all())
    days_by_date = {day.date: day for day in days if day.date}
    sections_by_id = {}
    for day in days:
        day.auto_legs, day.day_legs = [], []
        day.has_travel = False
        for section in getattr(day, "ordered_sections", []):
            section.placed_legs = []
            sections_by_id[section.pk] = section
            if section.section_type == Section.Type.TRAVEL:
                day.has_travel = True
    stray = []
    for leg in legs:
        day = leg.day_for(days_by_date)
        if day is None:
            leg.on_day = None
            stray.append(leg)
            continue
        day.day_legs.append(leg)
        leg.on_day = day
        section = sections_by_id.get(leg.section_id)
        if section is not None and section.day_id == day.pk:
            section.placed_legs.append(leg)
        else:
            day.auto_legs.append(leg)
    for day in days:
        day.travel_total = travel_total(day.day_legs)
    return stray


def attach_stays(days, stays):
    """Where you sleep each night (see the module docstring). Returns the stays whose check-in
    isn't one of the days' dates (they have no day to be shown on)."""
    for day in days:
        day.stay = None
        day.checking_in = []
        day.checking_out = []
        if not day.date:
            continue
        for stay in stays:
            if stay.check_in <= day.date < stay.check_out:
                day.stay = stay
            if stay.check_in == day.date:
                day.checking_in.append(stay)
            if stay.check_out == day.date:
                day.checking_out.append(stay)
    dates = {day.date for day in days if day.date}
    return [stay for stay in stays if stay.check_in not in dates]


MODE_ICONS = {"plane": "✈", "train": "🚆", "pov": "🚗", "rental_car": "🚙", "walking": "🚶", "other": "•"}
ACTIVITY_ICONS = {"tour": "🧭", "entry": "🎟", "ticket": "🎫", "table": "🍽", "car_hire": "🚙", "other": "•"}


def overview(days, not_booked=(), tasks=()):
    """Each day at a glance — its summary line on the web (see the module docstring). ``not_booked`` is
    ``booking_tasks.not_booked``'s list and ``tasks`` the trip's tasks after
    ``booking_tasks.attach`` (``task.item_day``)."""
    attention = {}
    for entry in not_booked:
        item = entry["item"]
        day = getattr(item, "on_day", None) if entry["kind"] == "leg" else None
        if entry["kind"] == "activity":
            day = item.day
        if entry["kind"] == "stay":
            day = next((d for d in days if d.date == item.check_in), None)
        if day is not None:
            attention[day.pk] = attention.get(day.pk, 0) + 1
    for task in tasks:
        if task.done:
            continue
        day = getattr(task, "item_day", None) or (task.day if task.day_id else None)
        if day is not None:
            attention[day.pk] = attention.get(day.pk, 0) + 1
    for day in days:
        legs = getattr(day, "day_legs", [])
        day.overnight = any(leg.departs_on_a_different_day for leg in legs)
        icons = []
        for leg in legs:
            icon = MODE_ICONS.get(leg.mode, "•")
            if icon not in icons:
                icons.append(icon)
        day.travel_icons = "".join(icons)
        if len(legs) == 1:
            day.travel_summary = f"{legs[0].origin} → {legs[0].destination}"
        elif legs:
            day.travel_summary = getattr(day, "travel_total", "") or f"{len(legs)} legs"
        else:
            day.travel_summary = ""
        titles = [activity.title for activity in getattr(day, "ordered_activities", [])][:2]
        day.highlights = titles or ([day.theme] if day.theme else [])
        day.attention = attention.get(day.pk, 0)


def open_day(days, today):
    """The day to open on arrival: today's while the trip is on, Day 1 before it, else None."""
    dated = [day for day in days if day.date]
    if not dated:
        return days[0] if days else None
    first, last = min(d.date for d in dated), max(d.date for d in dated)
    if today < first:
        return min(days, key=lambda d: d.day_number)
    if today > last:
        return None
    return next((day for day in dated if day.date == today), None)


def _fmt(clock):
    return clock.strftime("%I:%M %p").lstrip("0")


def timeline(days):
    """Each day's timeline, Any time and Food ideas (see the module docstring). A leg's time is
    its local departure where it leaves (never converted to the reader's zone); activities and
    meals are wall-clock times on the day."""
    for day in days:
        timed, any_time = [], []
        for leg in getattr(day, "day_legs", []):
            leg.icon = MODE_ICONS.get(leg.mode, "•")
            local = leg.departure_local
            if local is not None:
                timed.append({"kind": "leg", "item": leg, "time": local.time(), "label": leg.departure_local_str})
            else:
                any_time.append({"kind": "leg", "item": leg, "time": None, "label": ""})
        activities = getattr(day, "ordered_activities", [])
        for activity in activities:
            activity.icon = ACTIVITY_ICONS.get(activity.kind, "•")
            entry = {"kind": "activity", "item": activity, "time": activity.start_time, "label": activity.time_range}
            (timed if activity.start_time else any_time).append(entry)
        day.food_ideas = []
        for meal in getattr(day, "ordered_meals", []):
            if meal.reserved_time:
                timed.append({"kind": "meal", "item": meal, "time": meal.reserved_time,
                              "label": _fmt(meal.reserved_time)})
            else:
                day.food_ideas.append(meal)
        rank = {"leg": 0, "activity": 1, "meal": 2}
        timed.sort(key=lambda e: (e["time"], rank[e["kind"]]))
        day.timeline = timed
        day.any_time = any_time  # legs first (Meta order), then activities


def anchor(item):
    """The trip page id of an item's row or card (legs, stays, activities, meals), else of its
    day (sections, days)."""
    for model, prefix in ((TransportLeg, "leg"), (Lodging, "stay"), (TripActivity, "activity"), (Meal, "meal")):
        if isinstance(item, model):
            return f"{prefix}-{item.pk}"
    day = item if isinstance(item, Day) else getattr(item, "day", None)
    return f"day-{day.day_number}" if day is not None else ""


def _day_of(item, days_by_date):
    if isinstance(item, Day):
        return item
    if isinstance(item, TransportLeg):
        return getattr(item, "on_day", None)
    if isinstance(item, Lodging):
        return days_by_date.get(item.check_in)
    return getattr(item, "day", None)


def attach_links(trip, days):
    """Resolve the trip's prefetched ``item_links`` against the rows already loaded (see the
    module docstring); no queries."""
    days_by_date = {day.date: day for day in days if day.date}
    targets = {("day", day.pk): day for day in days}
    for leg in trip.transport.all():
        targets[("transportleg", leg.pk)] = leg
    for stay in trip.lodging.all():
        targets[("lodging", stay.pk)] = stay
    for day in days:
        day.good_to_know = []
        for section in getattr(day, "ordered_sections", []):
            section.day = day
            targets[("section", section.pk)] = section
        for meal in getattr(day, "ordered_meals", []):
            meal.day = day
            targets[("meal", meal.pk)] = meal
        for activity in getattr(day, "ordered_activities", []):
            activity.day = day
            targets[("tripactivity", activity.pk)] = activity
    for target in targets.values():
        target.refs = []
    sources = {("contact", c.pk): c for c in trip.contacts.all()}
    sources.update({("tripinfo", i.pk): i for i in trip.infos.all()})
    for source in sources.values():
        source.on = []
        source.is_info = isinstance(source, Contact) is False
    for link in trip.item_links.all():
        source = sources.get((link.source_type.model, link.source_id))
        target = targets.get((link.target_type.model, link.target_id))
        if source is None or target is None:
            continue
        target.refs.append(source)
        day = _day_of(target, days_by_date)
        source.on.append({"label": "whole day" if isinstance(target, Day) else item_label(target),
                          "anchor": anchor(target),
                          "day_number": day.day_number if day is not None else None})
        if isinstance(target, (Day, Section)) and day is not None and source not in day.good_to_know:
            day.good_to_know.append(source)
    for source in sources.values():
        source.on.sort(key=lambda on: (on["day_number"] is None, on["day_number"] or 0))
