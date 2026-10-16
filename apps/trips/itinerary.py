"""The day-by-day assembly both outputs need: the web trip page (``views.trip_detail``) and the
PDF booklet (``pdf.py``). Pure functions over the rows ``views._trip_page_queryset`` prefetched,
no queries; each sets attributes the templates read. (docs/plans/trip-page-ux.md, U1.)

- ``place_legs(trip)``: each leg on its day — ``day.day_legs`` (all of that date, in order),
  ``section.placed_legs`` (the travel section it's placed in), ``day.auto_legs`` (the rest),
  ``day.has_travel``, ``day.travel_total`` and ``leg.on_day``; returns the legs whose date is no
  day of the trip.
- ``travel_total(legs)``: "2 legs · ~3 h 15 min" when every leg has a time or an estimate.
- ``attach_stays(days, stays)``: where you sleep each night — ``day.stay`` (check-in ≤ date <
  check-out), ``day.checking_in`` / ``day.checking_out`` (stays starting / ending that day).
"""
from .models import Section


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
    """Where you sleep each night (see the module docstring)."""
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
