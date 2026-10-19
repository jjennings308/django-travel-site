"""An event's page tags and schema.org ``Event`` JSON-LD (site roadmap R22)."""
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.urls import reverse

from apps.core import seo

STATUS = {"scheduled": "EventScheduled", "postponed": "EventPostponed", "cancelled": "EventCancelled",
          "rescheduled": "EventRescheduled", "moved_online": "EventMovedOnline"}


def _when(day, at, zone):
    """A date, or a local date-time with its UTC offset when the event has a time and a known zone."""
    if at is None:
        return day.isoformat()
    moment = datetime.combine(day, at)
    try:
        moment = moment.replace(tzinfo=ZoneInfo(zone)) if zone else moment
    except (ZoneInfoNotFoundError, ValueError):
        pass
    return moment.isoformat()


def _place(event):
    country = event.place_country
    place = {"@type": "Place", "name": event.venue_name or (event.poi.name if event.poi_id else "") or event.place_name,
             "address": {"@type": "PostalAddress",
                         "addressLocality": event.city.name if event.city_id else event.location_text,
                         **({"addressCountry": country.iso_code} if country else {})}}
    if event.venue_address:
        place["address"]["streetAddress"] = event.venue_address
    for obj in (event, event.poi, event.city):
        if obj is not None and obj.latitude is not None and obj.longitude is not None:
            place["geo"] = {"@type": "GeoCoordinates", "latitude": float(obj.latitude), "longitude": float(obj.longitude)}
            break
    return place


def event_jsonld(event):
    timed = event.start_time and not event.is_all_day
    data = {
        "@context": "https://schema.org", "@type": "Event", "name": event.name,
        "startDate": _when(event.start_date, event.start_time if timed else None, event.timezone),
        "endDate": _when(event.end_date or event.start_date, event.end_time if timed else None, event.timezone),
        "eventStatus": f"https://schema.org/{STATUS.get(event.status, 'EventScheduled')}",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "location": _place(event),
        "url": seo.absolute(reverse("events:event_detail", args=[event.slug])),
    }
    description = seo.describe(event.short_description, event.description, limit=500)
    if description:
        data["description"] = description
    image = seo.media_url(event.display_media)
    if image:
        data["image"] = [image]
    return data


def event_meta(event):
    when = event.start_date.strftime("%-d %b %Y")
    return seo.meta(title=f"{event.name} · {when}",
                    description=seo.describe(event.short_description, event.description,
                                             f"{event.name}, {when}, {event.place_name}."),
                    image=seo.media_url(event.display_media), jsonld=event_jsonld(event))
