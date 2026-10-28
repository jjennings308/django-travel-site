"""Which notes an item shows (docs/plans/catalogue-notes.md).

An event shows its own notes, then its activity's, then its venue's (``Event.poi``); an activity its own,
then its venue's (``Activity.venue``); a place or a city its own. Approved notes for everyone; on catalogue pages a
member also sees their own notes still waiting for review, and staff see every note.
"""
from django.db.models import Q
from django.http import Http404

from apps.activities.models import Activity
from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event
from apps.locations.models import POI, City

from .models import CatalogueNote

#: URL kind -> (model, the note's field)
KINDS = {"poi": (POI, "poi"), "activity": (Activity, "activity"), "event": (Event, "event"), "city": (City, "city")}


def get_target(kind, slug):
    """A published catalogue item by kind and slug, else 404."""
    if kind not in KINDS:
        raise Http404
    model, _field = KINDS[kind]
    qs = model.objects.filter(slug=slug, approval_status=ApprovalStatus.APPROVED)
    if model is Activity:
        qs = qs.filter(visibility="public")
    target = qs.first()
    if target is None:
        raise Http404
    return target


#: URL kind -> its detail page's URL name
DETAIL = {"poi": "locations:poi_detail", "activity": "activities:activity_detail", "event": "events:event_detail",
          "city": "locations:city_detail"}


def target_url(target):
    from django.urls import reverse
    return reverse(DETAIL[kind_of(target)], args=[target.slug])


def kind_of(target):
    return next(kind for kind, (model, _field) in KINDS.items() if isinstance(target, model))


def visible(qs, user=None):
    if user is not None and user.is_authenticated and getattr(user, "can_access_staff", False):
        return qs
    shown = Q(approval_status=ApprovalStatus.APPROVED)
    if user is not None and user.is_authenticated:
        shown |= Q(created_by=user)
    return qs.filter(shown)


def sources(target):
    """(label, note field, pk) for the target's own notes (label None), then each one it inherits, in order."""
    found = [(None, f"{KINDS[kind_of(target)][1]}_id", target.pk)]
    if isinstance(target, Event):
        if target.related_activity_id:
            found.append((target.related_activity.name, "activity_id", target.related_activity_id))
        if target.poi_id:
            found.append((target.poi.name, "poi_id", target.poi_id))
    elif isinstance(target, Activity) and target.venue_id:
        found.append((target.venue.name, "poi_id", target.venue_id))
    return found


def notes_for(target, user=None):
    """The target's notes, own first, each inherited one marked ``note.from_name`` (its source's name)."""
    groups = sources(target)
    combined = Q()
    for _label, field, pk in groups:
        combined |= Q(**{field: pk})
    notes = list(visible(CatalogueNote.objects.filter(combined), user)
                 .select_related("poi", "activity", "event", "city", "created_by"))
    ordered = []
    for label, field, pk in groups:
        for note in notes:
            if getattr(note, field) == pk and note not in ordered:
                note.from_name = label
                ordered.append(note)
    return ordered
