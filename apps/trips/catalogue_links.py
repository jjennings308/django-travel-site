"""Link a trip's meals and sections to the catalogue (site roadmap R18).

A meal may name its catalogue place (a notable restaurant, market or bakery: most meals stay typed
text); a section a place or a catalogue activity. Choices are limited to the trip's cities
(``forms.catalogue_places`` / ``catalogue_activities``). On the day page, an unlinked meal or section
whose name matches exactly one of those (ignoring capitals, spacing and punctuation) gets a
suggestion — offered, never linked automatically; "Not this one" stores a ``TidyDismissal``.
"""
import re

from django.db.models import Q

from .forms import catalogue_activities, catalogue_places
from .models import Meal, Section, TidyDismissal

KINDS = {"meal": Meal, "section": Section}


def normalise(name):
    return " ".join(re.sub(r"[^\w\s]", " ", (name or "").casefold()).split())


def dismissal_key(kind, item_pk, target_kind, target_pk):
    return f"catalogue:{kind}:{item_pk}:{target_kind}:{target_pk}"


def _index(objs):
    found = {}
    for obj in objs:
        found.setdefault(normalise(obj.name), []).append(obj)
    return found


class Candidates:
    """The trip's catalogue places and activities by normalised name (two queries)."""

    def __init__(self, trip):
        self.places = _index(catalogue_places(trip))
        self.activities = _index(catalogue_activities(trip))

    def match(self, name, activities=True):
        """The one (target_kind, obj) whose name is ``name``, else None (none, or more than one)."""
        key = normalise(name)
        if not key:
            return None
        found = [("poi", p) for p in self.places.get(key, [])]
        if activities:
            found += [("activity", a) for a in self.activities.get(key, [])]
        return found[0] if len(found) == 1 else None


def attach_suggestions(trip, meals, sections):
    """Give each unlinked meal / section a ``catalogue_suggestion`` ({target_kind, target, key}) or None."""
    candidates = Candidates(trip)
    dismissed = set(TidyDismissal.objects.filter(trip=trip, key__startswith="catalogue:").values_list("key", flat=True))
    for kind, items in (("meal", meals), ("section", sections)):
        for item in items:
            item.catalogue_suggestion = None
            if item.poi_id or getattr(item, "activity_id", None):
                continue
            name = item.name if kind == "meal" else (item.content or {}).get("heading") or item.title
            found = candidates.match(name, activities=kind == "section")
            if found:
                target_kind, target = found
                key = dismissal_key(kind, item.pk, target_kind, target.pk)
                if key not in dismissed:
                    item.catalogue_suggestion = {"target_kind": target_kind, "target": target, "key": key}


def link(trip, item, target_kind, target_pk):
    """Set ``item.poi`` / ``item.activity`` to a target in the trip's catalogue choices; False if it isn't one."""
    if target_kind == "poi":
        target = catalogue_places(trip).filter(pk=target_pk).first()
    elif target_kind == "activity" and isinstance(item, Section):
        target = catalogue_activities(trip).filter(pk=target_pk).first()
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
