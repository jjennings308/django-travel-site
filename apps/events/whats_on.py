"""What's on (site roadmap R21): the month calendar, events near a place, and one event as iCalendar.

An event's dates are local dates where it happens, so a month is just a date range — no time-zone
shifting; only "today" depends on the reader (``timezone.localdate()`` under UserTimezoneMiddleware).
"""
import calendar as calendar_lib
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Q
from django.utils import timezone

from apps.activities.models import Activity
from apps.locations.models import POI, City, Country, Region

from .models import Event

NEARBY_KM = 50
SHOWN = 6
DAY_CAP = 3  # events listed in a calendar cell before "+N more"


def upcoming(qs, today=None):
    today = today or timezone.localdate()
    return qs.filter(Q(end_date__gte=today) | Q(end_date__isnull=True, start_date__gte=today))


def last_day(event):
    return event.end_date or event.start_date


# --- the month calendar -------------------------------------------------------------------------

@dataclass
class Day:
    date: date
    in_month: bool
    events: list = field(default_factory=list)

    @property
    def shown(self):
        return self.events[:DAY_CAP]

    @property
    def more(self):
        return max(0, len(self.events) - DAY_CAP)


def month_events(qs, year, month):
    """Events of ``qs`` running on any day of the month (one query), in start order."""
    first = date(year, month, 1)
    last = date(year, month, calendar_lib.monthrange(year, month)[1])
    return list(qs.filter(start_date__lte=last)
                .filter(Q(end_date__gte=first) | Q(end_date__isnull=True, start_date__gte=first))
                .order_by("start_date", "start_time", "name"))


def month_grid(events, year, month):
    """Weeks (Monday first) of ``Day``s; each event sits on every day it runs."""
    weeks = calendar_lib.Calendar(firstweekday=0).monthdatescalendar(year, month)
    days = {d: Day(d, d.month == month) for week in weeks for d in week}
    for event in events:
        start, end = event.start_date, last_day(event)
        for offset in range((end - start).days + 1):
            day = days.get(start + timedelta(days=offset))
            if day is not None:
                day.events.append(event)
    return [[days[d] for d in week] for week in weeks]


def neighbours(year, month):
    prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return prev_month, next_month


# --- events near a place ----------------------------------------------------------------------

def distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance (haversine)."""
    lat1, lon1, lat2, lon2 = map(math.radians, map(float, (lat1, lon1, lat2, lon2)))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def where(event):
    """The event's coordinates: its own, else its venue's, else its city's (None if none)."""
    for obj in (event, event.poi, event.city):
        if obj is not None and obj.latitude is not None and obj.longitude is not None:
            return obj.latitude, obj.longitude
    return None


TARGETS = {"city": City, "region": Region, "country": Country, "place": POI}


def events_for(kind, target, qs):
    """Upcoming events of ``qs`` for a place page, nearest/soonest first, each with ``distance_km``
    (None inside the place itself). One query."""
    qs = upcoming(qs).select_related("city", "poi", "category", *Event.PICTURE_RELATED).order_by("start_date", "name")
    if kind == "place":
        return [_at(e, None) for e in qs.filter(poi=target)[:SHOWN]]
    if kind == "region":
        return [_at(e, None) for e in qs.filter(city__region=target)[:SHOWN]]
    if kind == "country":
        return [_at(e, None) for e in qs.filter(Q(city__country=target) | Q(country=target))[:SHOWN]]
    # A city: its own events, then others within NEARBY_KM (a box in SQL, the exact distance here).
    if target.latitude is None or target.longitude is None:
        return [_at(e, None) for e in qs.filter(city=target)[:SHOWN]]
    lat, lon = float(target.latitude), float(target.longitude)
    dlat = NEARBY_KM / 111.0
    dlon = NEARBY_KM / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    box = Q()
    for prefix in ("", "poi__", "city__"):
        box |= Q(**{f"{prefix}latitude__range": (lat - dlat, lat + dlat),
                    f"{prefix}longitude__range": (lon - dlon, lon + dlon)})
    found = []
    for event in qs.filter(Q(city=target) | box)[:200]:
        if event.city_id == target.pk:
            found.append(_at(event, None))
            continue
        point = where(event)
        if point is not None:
            km = distance_km(lat, lon, *point)
            if km <= NEARBY_KM:
                found.append(_at(event, round(km)))
    found.sort(key=lambda e: (e.distance_km is not None, e.start_date))
    return found[:SHOWN]


def _at(event, km):
    event.distance_km = km
    return event


def things_to_do(kind, target):
    """Published activities for a place page, most popular first. One query."""
    qs = Activity.get_public_activities().select_related("category", "city", "country", *Activity.PICTURE_RELATED)
    where = {"place": Q(venue=target), "city": Q(city=target),
             "region": Q(region=target) | Q(city__region=target), "country": Q(country=target)}[kind]
    qs = qs.filter(where)
    return list(qs.order_by("-popularity_score", "-bucket_list_count", "name")[:SHOWN])


# --- one event as iCalendar ------------------------------------------------------------------

def _zone(name):
    try:
        return ZoneInfo(name) if name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


def event_ics(event, url):
    """``event`` as an .ics (bytes): timed in its own zone (TZID) when it has a start time, else all day
    (end date exclusive)."""
    from apps.core.ical import calendar, vevent
    cal = calendar("Event", event.name)
    zone = _zone(event.timezone)
    if event.start_time and not event.is_all_day:
        start = datetime.combine(event.start_date, event.start_time)
        end_day = event.end_date or event.start_date
        end = datetime.combine(end_day, event.end_time) if event.end_time else start + timedelta(hours=1)
        if end <= start:
            end = start + timedelta(hours=1)
        if zone is not None:
            start, end = start.replace(tzinfo=zone), end.replace(tzinfo=zone)
    else:
        start, end = event.start_date, last_day(event) + timedelta(days=1)
    lines = [event.short_description or "", url]
    cal.add_component(vevent(f"event-{event.pk}", event.name, start, end, event.venue_and_place,
                             "\n".join(line for line in lines if line), url))
    return cal.to_ical()
