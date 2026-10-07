"""Template filters for rendering UTC-stored times in a named IANA zone.

Usage in a template::

    {% load trip_time %}

    {{ leg.departure_at|at_zone:leg.origin_timezone }}
    {{ leg.arrival_at|at_zone_date:leg.destination_timezone }}
    {{ leg.origin_timezone|zone_abbrev }}
    {{ leg.origin_timezone|zone_abbrev:leg.departure_at }}
    {{ leg.origin_timezone|zone_offset }}

``at_zone`` renders the time only (``6:00 PM EST``); ``at_zone_date`` renders the
local calendar date (``Thu, Jan 15``). They are separate because a leg can
depart on one local day and arrive on the next.

For a custom pattern use the ``localtime`` tag — template filters take only one
argument, and a pattern needs both the zone and the format::

    {% localtime leg.arrival_at leg.destination_timezone "g:i A T" %}

``zone_abbrev`` / ``zone_offset`` describe *today* unless you pass a moment
(``zone_abbrev:leg.departure_at``). Always pass the leg's timestamp when
rendering an itinerary, or a January trip will be labelled ``MDT`` in summer.

Do NOT chain Django's built-in ``|time`` or ``|date`` after a zone filter —
both are registered with ``expects_localtime=True``, so the template engine
rewrites the value back into the currently active timezone (UTC here) and
silently undoes the conversion. Use ``at_zone``, which formats in place.

If the zone is blank or unresolvable the value is rendered in UTC rather than
suppressed, so a missing timezone degrades instead of blanking the page.
"""

from datetime import date, datetime

from django import template
from django.utils import timezone as django_timezone

from ..models import format_local_date, format_local_time, get_timezone, localize

register = template.Library()


def _zone_for(zone_name):
    """Resolve an IANA name, tolerating the ``"None"`` a template yields."""
    if not isinstance(zone_name, str) or not zone_name:
        return None
    return get_timezone(zone_name)


def _at(when, zone):
    """Return ``when`` as an aware datetime in ``zone``; default to now."""
    if isinstance(when, datetime):
        if django_timezone.is_naive(when):
            when = django_timezone.make_aware(when, django_timezone.UTC)
        return django_timezone.localtime(when, zone)
    if isinstance(when, date):
        moment = datetime(when.year, when.month, when.day, 12, 0)
        return django_timezone.make_aware(moment, django_timezone.UTC).astimezone(zone)
    return django_timezone.now().astimezone(zone)


def _to_zone(value, zone_name):
    """Coerce an aware datetime into ``zone_name``, defaulting to UTC.

    Thin wrapper over ``models.localize`` that additionally tolerates the
    string ``"None"`` a template yields for a missing variable.
    """
    if not isinstance(value, datetime):
        return None
    return localize(value, zone_name)


@register.filter(name="at_zone")
def at_zone(value, zone_name):
    """Convert ``value`` into ``zone_name`` and render it as a local time.

    Renders the *time only* (``6:00 PM EST``), matching
    ``TransportLeg.departure_local_str``. Pair it with ``at_zone_date`` for the
    local calendar date, or use the ``localtime`` tag for a custom pattern.
    """
    return format_local_time(value, zone_name) or ""


@register.filter(name="at_zone_date")
def at_zone_date(value, zone_name):
    """Render ``value``'s local calendar date in ``zone_name``.

    Renders as ``Thu, Jan 15``. Kept separate from ``at_zone`` because a
    leg can depart on one local day and arrive on the next.
    """
    return format_local_date(value, zone_name) or ""


@register.simple_tag(name="localtime")
def localtime(value, zone_name, fmt):
    """Render ``value`` in ``zone_name`` using the strftime pattern ``fmt``.

    A tag rather than a filter because template filters take a single
    argument, and a custom pattern needs both the zone and the format::

        {% localtime leg.departure_at leg.origin_timezone "g:i A T" %}
    """
    local = _to_zone(value, zone_name)
    return "" if local is None else local.strftime(fmt)


@register.filter(name="in_zone_time")
@register.filter(name="in_zone")
def in_zone(value, zone_name):
    """Return ``value`` as an aware datetime in ``zone_name``.

    Returns a datetime for callers that need to do arithmetic (durations,
    comparisons). Do not pass the result to ``|date``/``|time`` — see the
    module docstring.
    """
    return _to_zone(value, zone_name)


@register.filter(name="zone_abbrev")
def zone_abbrev(zone_name, when=None):
    """Abbreviation for an IANA zone, e.g. ``MST``, or ``''``.

    Pass ``when`` (a datetime or date) to describe that moment rather than
    today — a leg in January is ``MST`` even though it is ``MDT`` now.
    """
    zone = _zone_for(zone_name)
    if zone is None:
        return ""
    return _at(when, zone).tzname() or ""


@register.filter(name="zone_offset")
def zone_offset(zone_name, when=None):
    """UTC offset for an IANA zone, e.g. ``-07:00``, or ``''``.

    Pass ``when`` to describe that moment rather than today.
    """
    zone = _zone_for(zone_name)
    if zone is None:
        return ""
    offset = _at(when, zone).utcoffset()
    if offset is None:
        return ""
    total = int(offset.total_seconds())
    sign = "-" if total < 0 else "+"
    hours, minutes = divmod(abs(total), 3600)
    return f"{sign}{hours:02d}:{minutes // 60:02d}"
