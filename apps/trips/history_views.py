"""A trip's change history and undo (site roadmap R8); the rules are in ``changes.py``.

``trips:trip_history`` — anyone who can see the trip: newest first, filter by day, person and kind,
each line linking to its item on the trip page. ``trips:change_undo`` — editors: undo a change
(only the item's newest, and only if it hasn't been edited since) or restore a removed item.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import changes
from .models import Trip, TripChange

ANCHORS = {"transportleg": "leg", "lodging": "stay", "tripactivity": "activity", "meal": "meal",
           "confirmation": "confirmation"}


def _anchor(change):
    if change.kind == TripChange.Kind.REMOVED:
        return ""
    prefix = ANCHORS.get(change.item_type)
    if prefix and change.item_id:
        return f"{prefix}-{change.item_id}"
    if change.day_id and change.day is not None:
        return f"day-{change.day.day_number}"
    return ""


@login_required
def trip_history(request, pk):
    trip = get_object_or_404(Trip.objects.visible_to(request.user), pk=pk)
    can_edit = trip.can(request.user, "edit")
    found = trip.changes.select_related("actor", "day").order_by("-when", "-id")
    day, person, kind = request.GET.get("day", ""), request.GET.get("person", ""), request.GET.get("kind", "")
    if day.isdigit():
        found = found.filter(day_id=day)
    if person == "none":
        found = found.filter(actor=None)
    elif person.isdigit():
        found = found.filter(actor_id=person)
    if kind in TripChange.Kind.values:
        found = found.filter(kind=kind)
    page = Paginator(found, 50).get_page(request.GET.get("page"))
    latest = changes.latest_change_ids(trip) if can_edit else {}
    for change in page:
        change.anchor = _anchor(change)
        change.undoable = can_edit and changes.can_undo(change, latest)
    people = (trip.changes.exclude(actor=None).values_list("actor_id", "actor__first_name", "actor__last_name",
                                                           "actor__username").distinct())
    return render(request, "trips/trip_history.html", {
        "trip": trip, "page_obj": page, "can_edit": can_edit, "days": trip.days.order_by("day_number"),
        "people": sorted({(pk, f"{first} {last}".strip() or username) for pk, first, last, username in people},
                         key=lambda p: p[1].lower()),
        "kinds": TripChange.Kind.choices, "day": day, "person": person, "kind": kind,
    })


@login_required
@require_POST
def change_undo(request, pk, change_pk):
    trip = get_object_or_404(Trip.objects.visible_to(request.user), pk=pk)
    if not trip.can(request.user, "edit"):
        raise PermissionDenied
    change = get_object_or_404(TripChange, pk=change_pk, trip=trip)
    try:
        if change.kind == TripChange.Kind.REMOVED:
            changes.restore(change, actor=request.user)
            messages.success(request, f"Restored. “{change.summary.removeprefix('Removed ')}” is back.")
        elif change.kind == TripChange.Kind.CHANGED:
            changes.undo(change)
            messages.success(request, "Undone. That's recorded too, so it can be undone in turn.")
        else:
            raise changes.CannotUndo("Additions can't be undone here; remove the item instead.")
    except changes.CannotUndo as reason:
        messages.error(request, f"Couldn't undo: {reason}")
    return redirect("trips:trip_history", pk=trip.pk)
