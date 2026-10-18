"""Recording changes to a trip's plan, and telling the people on it (site roadmap R7).

Signals on the tracked models write a ``TripChange`` per real change, with a readable summary
("Changed Frankfurt Hbf → Augsburg Hbf: departs 10:00 AM CEST → 10:30 AM CEST"). ``pre_save``
reads the stored row (one query per save of a tracked object) so only fields that actually
changed are listed. The actor is whoever is signed in (``apps.core.current``; None in scripts).

* ``batch(summary, trip=None, actor=None)`` silences the per-item records inside it and writes one line
  instead — imports, turning tables into legs, applying tidy suggestions.
* A removal is recorded only for the object deleted on purpose: things deleted with it (a day's
  meals, a confirmation's links and files, a whole trip in the admin) are not listed one by one.
* A leg whose times or date change within ``URGENT_DAYS`` of departure tells everyone at once
  (after commit); everything else waits for ``manage.py send_trip_digests``.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import dateformat, timezone

from apps.core.current import get_user

from .models import (
    Confirmation, ConfirmationFile, ConfirmationLink, Day, Lodging, Meal, Section, TransportLeg, Trip, TripActivity,
    TripChange, TripGrant, item_label,
)

URGENT_DAYS = 7
_batch = ContextVar("sbl_change_batch", default=None)


def _date(value):
    return f"{value:%a %b} {value.day}" if value else "none"


def _time(value):
    return dateformat.format(value, "g:i A") if value else "none"


def _text(value):
    return str(value) if value not in (None, "") else "none"


def _day_number(day_id):
    return Day.objects.filter(pk=day_id).values_list("day_number", flat=True).first() if day_id else None


def _city(obj):
    return str(obj.city) if getattr(obj, "city_id", None) else "none"


# model -> (item type, label(obj), trip_id(obj), [(field attname, label, format(obj) or None)])
# A format of None means "say it changed" (long text, JSON).
TRACKED = {
    TransportLeg: ("leg", lambda o: f"{o.origin} → {o.destination}", lambda o: o.trip_id, [
        ("mode", "mode", lambda o: o.get_mode_display()),
        ("origin", "from", lambda o: _text(o.origin)),
        ("destination", "to", lambda o: _text(o.destination)),
        ("operator", "operator", lambda o: _text(o.operator)),
        ("service_number", "service", lambda o: _text(o.service_number)),
        ("date", "date", lambda o: _date(o.date)),
        ("departure_at", "departs", lambda o: o.departure_local_str or "no time"),
        ("arrival_at", "arrives", lambda o: o.arrival_local_str or "no time"),
        ("notes", "notes", None),
    ]),
    Lodging: ("stay", lambda o: f"stay {o.name}", lambda o: o.trip_id, [
        ("name", "name", lambda o: _text(o.name)),
        ("check_in", "check-in", lambda o: _date(o.check_in)),
        ("check_out", "check-out", lambda o: _date(o.check_out)),
        ("address", "address", None),
        ("city_id", "city", _city),
    ]),
    TripActivity: ("activity", lambda o: f"“{o.title}”", lambda o: o.trip_id, [
        ("title", "title", lambda o: _text(o.title)),
        ("day_id", "day", lambda o: f"Day {_day_number(o.day_id)}"),
        ("start_time", "starts", lambda o: _time(o.start_time)),
        ("end_time", "ends", lambda o: _time(o.end_time)),
        ("provider", "provider", lambda o: _text(o.provider)),
        ("place_text", "place", lambda o: _text(o.place_text)),
        ("poi_id", "place", lambda o: _text(o.poi)),
        ("notes", "notes", None),
    ]),
    Meal: ("meal", lambda o: f"{o.get_meal_type_display().lower()} at {o.name}",
           lambda o: Day.objects.filter(pk=o.day_id).values_list("trip_id", flat=True).first(), [
        ("name", "name", lambda o: _text(o.name)),
        ("meal_type", "meal", lambda o: o.get_meal_type_display()),
        ("day_id", "day", lambda o: f"Day {_day_number(o.day_id)}"),
        ("reserved_time", "reservation", lambda o: _time(o.reserved_time)),
        ("reservation_notes", "booking notes", None),
    ]),
    Section: ("section", lambda o: f"“{o.title or o.get_section_type_display()}” on Day {_day_number(o.day_id)}",
              lambda o: Day.objects.filter(pk=o.day_id).values_list("trip_id", flat=True).first(), [
        ("title", "title", lambda o: _text(o.title)),
        ("content", "text", None),
        ("day_id", "day", lambda o: f"Day {_day_number(o.day_id)}"),
    ]),
    Day: ("day", lambda o: f"Day {o.day_number}", lambda o: o.trip_id, [
        ("date", "date", lambda o: _date(o.date)),
        ("city_id", "city", _city),
        ("theme", "theme", lambda o: _text(o.theme)),
    ]),
    Confirmation: ("confirmation", lambda o: f"confirmation {o.confirmation_number}", lambda o: o.trip_id, [
        ("confirmation_number", "number", lambda o: _text(o.confirmation_number)),
        ("provider", "provider", lambda o: _text(o.provider)),
        ("label", "label", lambda o: _text(o.label)),
        ("url", "booking link", None),
        ("cost", "cost", lambda o: _text(o.cost)),
        ("notes", "notes", None),
    ]),
}


def _fields(model):
    names = {f.attname for f in model._meta.concrete_fields}
    return [spec for spec in TRACKED[model][3] if spec[0] in names]


def record(trip_id, kind, summary, item=None, actor=None):
    """Write one change, or count it towards the enclosing ``batch``."""
    if not trip_id:
        return None
    current = _batch.get()
    if current is not None and current["trip_id"] in (None, trip_id):
        current["counts"][trip_id] = current["counts"].get(trip_id, 0) + 1
        return None
    return TripChange.objects.create(
        trip_id=trip_id, actor=actor if actor is not None else get_user(), kind=kind,
        item_type=type(item).__name__.lower() if item is not None else "", item_id=getattr(item, "pk", None),
        summary=summary[:500])


@contextmanager
def batch(summary, trip=None, actor=None):
    """One "<summary> (N changes)" line per trip instead of a line per item, for bulk operations.
    ``trip=None`` covers whichever trips are touched (an import creates its trip inside)."""
    state = {"trip_id": getattr(trip, "pk", None), "counts": {}}
    token = _batch.set(state)
    try:
        yield state
    finally:
        _batch.reset(token)
    for trip_id, count in state["counts"].items():
        if Trip.objects.filter(pk=trip_id).exists():
            noun = "change" if count == 1 else "changes"
            record(trip_id, TripChange.Kind.CHANGED, f"{summary} ({count} {noun})", actor=actor)


def _deleted_on_purpose(instance, origin):
    if origin is None:
        return True
    if hasattr(origin, "model"):  # a queryset .delete()
        return origin.model is type(instance)
    return type(origin) is type(instance) and origin.pk == instance.pk


# -------------------------------------------------------------------------- signals: items

def _before(sender, instance, raw=False, **kwargs):
    if raw or not instance.pk:
        instance._change_old = None
        return
    instance._change_old = sender._base_manager.filter(pk=instance.pk).first()


def _after(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    item_type, label, trip_of, _ = TRACKED[sender]
    old = getattr(instance, "_change_old", None)
    if created or old is None:
        record(trip_of(instance), TripChange.Kind.ADDED, f"Added {label(instance)}", instance)
        return
    parts, changed = [], set()
    for attname, name, fmt in _fields(sender):
        before, after = getattr(old, attname), getattr(instance, attname)
        if before == after:
            continue
        changed.add(attname)
        parts.append(f"{name} changed" if fmt is None else f"{name} {fmt(old)} → {fmt(instance)}")
    if not parts:
        return
    record(trip_of(instance), TripChange.Kind.CHANGED, f"Changed {label(old)}: {'; '.join(parts)}", instance)
    if sender is TransportLeg and changed & {"departure_at", "arrival_at", "date"}:
        _maybe_urgent(old, instance)


def _gone(sender, instance, origin=None, **kwargs):
    if not _deleted_on_purpose(instance, origin):
        return
    _, label, trip_of, _ = TRACKED[sender]
    trip_id = trip_of(instance)  # a meal's or section's day still exists: it wasn't deleted with it
    if trip_id and Trip.objects.filter(pk=trip_id).exists():
        record(trip_id, TripChange.Kind.REMOVED, f"Removed {label(instance)}", instance)


for _model in TRACKED:
    pre_save.connect(_before, sender=_model, dispatch_uid=f"trip_change_before_{_model.__name__}")
    post_save.connect(_after, sender=_model, dispatch_uid=f"trip_change_after_{_model.__name__}")
    post_delete.connect(_gone, sender=_model, dispatch_uid=f"trip_change_gone_{_model.__name__}")


# --------------------------------------------------------- signals: links and ticket files

@receiver(post_save, sender=ConfirmationLink, dispatch_uid="trip_change_link_added")
def _link_added(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        number = instance.confirmation.confirmation_number
        record(instance.confirmation.trip_id, TripChange.Kind.ADDED,
               f"Added confirmation {number} to {_item_name(instance)}", instance.confirmation)


@receiver(post_delete, sender=ConfirmationLink, dispatch_uid="trip_change_link_removed")
def _link_removed(sender, instance, origin=None, **kwargs):
    if _deleted_on_purpose(instance, origin):
        confirmation = Confirmation.objects.filter(pk=instance.confirmation_id).first()
        if confirmation:
            record(confirmation.trip_id, TripChange.Kind.REMOVED,
                   f"Removed confirmation {confirmation.confirmation_number} from {_item_name(instance)}",
                   confirmation)


@receiver(post_save, sender=ConfirmationFile, dispatch_uid="trip_change_file_added")
def _file_added(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        record(instance.confirmation.trip_id, TripChange.Kind.ADDED,
               f"Added {instance.original_name} to confirmation {instance.confirmation.confirmation_number}",
               instance.confirmation)


@receiver(post_delete, sender=ConfirmationFile, dispatch_uid="trip_change_file_removed")
def _file_removed(sender, instance, origin=None, **kwargs):
    if _deleted_on_purpose(instance, origin):
        confirmation = Confirmation.objects.filter(pk=instance.confirmation_id).first()
        if confirmation:
            record(confirmation.trip_id, TripChange.Kind.REMOVED,
                   f"Removed {instance.original_name} from confirmation {confirmation.confirmation_number}",
                   confirmation)


def _item_name(link):
    item = link.item
    return item_label(item) if item is not None else "an item"


# ------------------------------------------------------------------------- who is told

def recipients(trip, exclude_user_id=None):
    """Active people with a grant on ``trip`` who want change emails, minus whoever made it."""
    grants = (TripGrant.objects.filter(trip=trip, notify_changes=True, user__is_active=True)
              .select_related("user"))
    return [grant.user for grant in grants if grant.user_id != exclude_user_id]


def _maybe_urgent(old, leg):
    """A time or date change to a leg departing within ``URGENT_DAYS``: tell everyone now."""
    today = timezone.localdate()
    soon = today + timedelta(days=URGENT_DAYS)

    def departs(item):
        if item.departure_at:
            return timezone.localtime(item.departure_at).date()
        return item.date

    if not any(d and today <= d <= soon for d in (departs(old), departs(leg))):
        return
    actor = get_user()
    trip_id = leg.trip_id

    def send():
        from apps.notifications.services import notify
        trip = Trip.objects.filter(pk=trip_id, deleted_at=None).first()
        if trip is None:
            return
        name = f"{leg.operator} {leg.service_number}".strip()
        what = f"{name + ' ' if name else ''}{leg.origin} → {leg.destination}"
        now = (f"now departs {_date(departs(leg))} {leg.departure_local_str}" if leg.departure_at
               else f"is now on {_date(leg.date)}, no times yet")
        was = (f"was {_date(departs(old))} {old.departure_local_str}" if old.departure_at
               else f"was {_date(old.date)}")
        message = f"Time change on “{trip.name}”: {what} {now} ({was})."
        url = reverse("trips:trip_detail", args=[trip.pk]) + f"#leg-{leg.pk}"
        for user in recipients(trip, exclude_user_id=getattr(actor, "pk", None)):
            notify(user, "trip_changed", f"Time change: {what}", message, url, obj=trip)

    transaction.on_commit(send)
