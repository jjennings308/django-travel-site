"""iCalendar building blocks shared by the trip feed (trips, site roadmap R4) and a single event's
"Add to my calendar" file (events, R21). Stable UIDs (``<uid>@sharebucketlist.com``) let a calendar app
replace an item it already has instead of adding a second copy."""
from datetime import datetime, timezone as dt_timezone

from icalendar import Calendar, Event

DOMAIN = "sharebucketlist.com"


def calendar(prodid, name=""):
    """An empty VCALENDAR with the usual header lines."""
    cal = Calendar()
    cal.add("prodid", f"-//ShareBucketList//{prodid}//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    if name:
        cal.add("x-wr-calname", name)
    return cal


def vevent(uid, summary, start, end, location="", description="", url="", now=None):
    """One VEVENT. ``start`` / ``end``: dates (all day, end exclusive), naive datetimes (floating local
    time) or aware ones (written with their zone: UTC as ``Z``, a zoneinfo zone as ``TZID``)."""
    ev = Event()
    ev.add("uid", f"{uid}@{DOMAIN}")
    ev.add("dtstamp", now or datetime.now(dt_timezone.utc))
    ev.add("summary", summary)
    ev.add("dtstart", start)
    ev.add("dtend", end)
    if location:
        ev.add("location", location)
    if description:
        ev.add("description", description)
    if url:
        ev.add("url", url)
    return ev
