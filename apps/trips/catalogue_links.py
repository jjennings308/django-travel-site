"""Link a trip's meals and sections to the catalogue (site roadmap R18).

A meal may name its catalogue place (a notable restaurant, market or bakery: most meals stay typed
text); a section a place, a catalogue activity or a dated event (catalogue-notes N4). Choices are limited
to the trip's cities (``forms.catalogue_places`` / ``catalogue_activities``) and, for events, to those during
the trip (``catalogue_events``); a section whose name matches an activity with an event on that section's
day is offered the event (Oktoberfest on Sep 21, 2027 → Oktoberfest 2027). On the day page, an unlinked meal or section
whose name matches exactly one of those (ignoring capitals, spacing, punctuation and accents, with
German ö/ä/ü written either way: "Zur Höll" = "Zur Hoell" = "Zur Holl") gets a
suggestion — offered, never linked automatically; "Not this one" stores a ``TidyDismissal``.
"""
import re
import unicodedata

from django.db.models import Q

from .forms import catalogue_activities, catalogue_events, catalogue_places
from .models import Meal, Section, TidyDismissal

KINDS = {"meal": Meal, "section": Section}


def normalise(name):
    return " ".join(re.sub(r"[^\w\s]", " ", (name or "").casefold()).split())


GERMAN = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue"})


def _strip_accents(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def match_keys(name):
    """The forms a name may match in: as typed, accents dropped (ö → o) and German umlauts spelled out
    (ö → oe); ß is already "ss" (casefold). Two names match when any keys agree."""
    base = normalise(name)
    if not base:
        return set()
    return {base, _strip_accents(base), _strip_accents(base.translate(GERMAN))}


def dismissal_key(kind, item_pk, target_kind, target_pk):
    return f"catalogue:{kind}:{item_pk}:{target_kind}:{target_pk}"


def _index(objs):
    found = {}
    for obj in objs:
        for key in match_keys(obj.name):
            found.setdefault(key, []).append(obj)
    return found


def _lookup(index, keys):
    """Objects under any of ``keys``, each once, in a stable order."""
    seen = {}
    for key in sorted(keys):
        for obj in index.get(key, []):
            seen.setdefault(obj.pk, obj)
    return list(seen.values())


class Candidates:
    """The trip's catalogue places, activities and events by normalised name (three queries)."""

    def __init__(self, trip):
        self.places = _index(catalogue_places(trip))
        self.activities = _index(catalogue_activities(trip))
        self.event_list = list(catalogue_events(trip))
        self.events = _index(self.event_list)

    def event_on(self, activity, day_date):
        """The one event of ``activity`` running on ``day_date``, else None."""
        found = [e for e in self.event_list if e.related_activity_id == activity.pk and day_date
                 and e.start_date <= day_date <= (e.end_date or e.start_date)]
        return found[0] if len(found) == 1 else None

    def match(self, name, activities=True, day_date=None):
        """The one (target_kind, obj) whose name is ``name``, else None (none, or more than one). With
        activities, an activity that has an event on ``day_date`` is offered as that event."""
        keys = match_keys(name)
        if not keys:
            return None
        found = [("poi", p) for p in _lookup(self.places, keys)]
        if activities:
            for activity in _lookup(self.activities, keys):
                event = self.event_on(activity, day_date)
                found.append(("event", event) if event is not None else ("activity", activity))
            found += [("event", e) for e in _lookup(self.events, keys) if ("event", e) not in found]
        return found[0] if len(found) == 1 else None


def attach_suggestions(trip, meals, sections):
    """Give each unlinked meal / section a ``catalogue_suggestion`` ({target_kind, target, key}) or None."""
    candidates = Candidates(trip)
    dismissed = set(TidyDismissal.objects.filter(trip=trip, key__startswith="catalogue:").values_list("key", flat=True))
    for kind, items in (("meal", meals), ("section", sections)):
        for item in items:
            item.catalogue_suggestion = None
            if item.poi_id or getattr(item, "activity_id", None) or getattr(item, "event_id", None):
                continue
            name = item.name if kind == "meal" else (item.content or {}).get("heading") or item.title
            found = candidates.match(name, activities=kind == "section", day_date=item.day.date)
            if found:
                target_kind, target = found
                key = dismissal_key(kind, item.pk, target_kind, target.pk)
                if key not in dismissed:
                    item.catalogue_suggestion = {"target_kind": target_kind, "target": target, "key": key}


def link(trip, item, target_kind, target_pk):
    """Set ``item.poi`` / ``.activity`` / ``.event`` to a target in the trip's catalogue choices; False if it isn't one."""
    if target_kind == "poi":
        target = catalogue_places(trip).filter(pk=target_pk).first()
    elif target_kind == "activity" and isinstance(item, Section):
        target = catalogue_activities(trip).filter(pk=target_pk).first()
    elif target_kind == "event" and isinstance(item, Section):
        target = catalogue_events(trip).filter(pk=target_pk).first()
    else:
        target = None
    if target is None:
        return False
    setattr(item, target_kind, target)
    item.save(update_fields=[target_kind])
    return True


def import_matches(parsed_days):
    """For ``import_itinerary``'s dry run: meal names and section titles that exactly match an approved
    catalogue place or published activity anywhere (the new trip has no cities yet). Yields
    (day_number, what, name, label) — never links anything."""
    from apps.activities.models import Activity
    from apps.approval_system.models import ApprovalStatus
    from apps.locations.models import POI
    wanted = {}
    for day in parsed_days:
        number = day.get("day_number")
        for meal in day.get("meals") or []:
            wanted.setdefault(normalise(meal.get("name")), []).append((number, "meal", meal.get("name")))
        for section in day.get("sections") or []:
            content = section.get("content") or {}
            title = content.get("heading") or section.get("title")
            wanted.setdefault(normalise(title), []).append((number, "section", title))
    wanted.pop("", None)
    if not wanted:
        return []
    names = {name for rows in wanted.values() for _, _, name in rows}
    exact = Q()
    for name in names:
        exact |= Q(name__iexact=name.strip())
    found = {}
    for poi in POI.objects.filter(exact, approval_status=ApprovalStatus.APPROVED).select_related("city"):
        found.setdefault(normalise(poi.name), []).append(f"place {poi.name}, {poi.city.name}")
    for activity in Activity.get_public_activities().filter(exact):
        found.setdefault(normalise(activity.name), []).append(f"activity {activity.name}")
    return [(number, what, name, " / ".join(found[key]))
            for key in found for number, what, name in wanted.get(key, [])]
