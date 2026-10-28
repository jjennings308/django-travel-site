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
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import dateformat, timezone

from apps.core.current import get_user

from .models import (
    BookingTask, Confirmation, ConfirmationFile, ConfirmationLink, Day, ItemLink, Lodging, Meal, OptionGroup, Section,
    TaskLink, TransportLeg, Trip, TripActivity, TripChange, TripGrant, TripIdea, item_label,
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
def _booking(o):
    """"needed" / "not needed" (booking-todos K2: an item's No booking needed)."""
    return "not needed" if o.no_booking else "needed"


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
        ("no_booking", "booking", _booking),
    ]),
    Lodging: ("stay", lambda o: f"stay {o.name}", lambda o: o.trip_id, [
        ("name", "name", lambda o: _text(o.name)),
        ("check_in", "check-in", lambda o: _date(o.check_in)),
        ("check_out", "check-out", lambda o: _date(o.check_out)),
        ("address", "address", None),
        ("city_id", "city", _city),
        ("no_booking", "booking", _booking),
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
        ("no_booking", "booking", _booking),
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
    # A "choose one" (day-first plan P4): picking and reopening are recorded; undoing a pick reopens it.
    OptionGroup: ("choice", lambda o: f"“{o.prompt}” on Day {_day_number(o.day_id)}", lambda o: o.trip_id, [
        ("prompt", "question", lambda o: _text(o.prompt)),
        ("state", "decision", lambda o: o.summary()),
        ("start_time", "time", lambda o: _time(o.start_time)),
    ]),
    # An idea on the shelf (P6): added, renamed, removed. Putting it on a day records the item made.
    TripIdea: ("idea", lambda o: f"idea “{o.title}”", lambda o: o.trip_id, [
        ("title", "title", lambda o: _text(o.title)),
        ("notes", "notes", None),
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


def record(trip_id, kind, summary, item=None, actor=None, day_id=None, before=None):
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
        summary=summary[:500], day_id=day_id, before=before)


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


@contextmanager
def quiet():
    """Record nothing inside (restoring an item records its own one line)."""
    token = _batch.set({"trip_id": None, "counts": {}})
    try:
        yield
    finally:
        _batch.reset(token)


def day_id_of(instance):
    """The trip day a change is about, for the history's day filter (R8)."""
    if isinstance(instance, Day):
        return instance.pk
    if isinstance(instance, (TransportLeg, Lodging)):
        when = instance.date if isinstance(instance, TransportLeg) else instance.check_in
        if not when:
            return None
        return Day.objects.filter(trip_id=instance.trip_id, date=when).values_list("pk", flat=True).first()
    return getattr(instance, "day_id", None)


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
        record(trip_of(instance), TripChange.Kind.ADDED, f"Added {label(instance)}", instance,
               day_id=day_id_of(instance))
        return
    parts, changed, values = [], set(), {"before": {}, "after": {}}
    for attname, name, fmt in _fields(sender):
        before, after = getattr(old, attname), getattr(instance, attname)
        if before == after:
            continue
        changed.add(attname)
        values["before"][attname], values["after"][attname] = before, after
        parts.append(f"{name} changed" if fmt is None else f"{name} {fmt(old)} → {fmt(instance)}")
    if not parts:
        return
    record(trip_of(instance), TripChange.Kind.CHANGED, f"Changed {label(old)}: {'; '.join(parts)}", instance,
           day_id=day_id_of(instance), before=values)
    if sender is TransportLeg and changed & {"departure_at", "arrival_at", "date"}:
        _maybe_urgent(old, instance)


def _gone(sender, instance, origin=None, **kwargs):
    if not _deleted_on_purpose(instance, origin):
        return
    _, label, trip_of, _ = TRACKED[sender]
    trip_id = trip_of(instance)  # a meal's or section's day still exists: it wasn't deleted with it
    if trip_id and Trip.objects.filter(pk=trip_id).exists():
        record(trip_id, TripChange.Kind.REMOVED, f"Removed {label(instance)}", instance,
               day_id=None if sender is Day else day_id_of(instance),
               before=getattr(instance, "_change_snapshot", None))


def _snap(sender, instance, origin=None, **kwargs):
    """Before a restorable item is deleted on purpose, keep what restoring it needs (its links
    are deleted before ``post_delete`` runs)."""
    if sender in RESTORABLE and _deleted_on_purpose(instance, origin):
        instance._change_snapshot = snapshot(instance)


for _model in TRACKED:
    pre_save.connect(_before, sender=_model, dispatch_uid=f"trip_change_before_{_model.__name__}")
    post_save.connect(_after, sender=_model, dispatch_uid=f"trip_change_after_{_model.__name__}")
    post_delete.connect(_gone, sender=_model, dispatch_uid=f"trip_change_gone_{_model.__name__}")
    pre_delete.connect(_snap, sender=_model, dispatch_uid=f"trip_change_snap_{_model.__name__}")


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


# ------------------------------------------------------------------- undo and restore (R8)

# Removed items that can be brought back (days, confirmations and trips can't: admin only).
RESTORABLE = {TransportLeg: "leg", Lodging: "stay", TripActivity: "activity", Meal: None, Section: None}
MODELS = {model.__name__.lower(): model for model in TRACKED}


class CannotUndo(Exception):
    """Why a change can't be undone or an item restored (shown to the editor)."""


def snapshot(instance):
    """Everything restoring ``instance`` needs: its row and many-to-many (Django's serializer),
    the confirmations and contacts/notes linked to it, and the to-dos covering it (``task_links``,
    booking-todos K1)."""
    from django.contrib.contenttypes.models import ContentType
    from django.core import serializers
    content_type = ContentType.objects.get_for_model(instance)
    takes_tasks = RESTORABLE.get(type(instance)) is not None
    return {
        "object": serializers.serialize("python", [instance])[0],
        "links": list(ConfirmationLink.objects.filter(content_type=content_type, object_id=instance.pk)
                      .values_list("confirmation_id", flat=True)),
        "refs": list(ItemLink.objects.filter(target_type=content_type, target_id=instance.pk)
                     .values("source_type_id", "source_id")),
        "task_links": list(TaskLink.objects.filter(content_type=content_type, object_id=instance.pk)
                           .values_list("task_id", flat=True)) if takes_tasks else [],
    }


def latest_change_ids(trip):
    """{(item_type, item_id): id of its newest change} — only the newest can be undone."""
    from django.db.models import Max
    rows = trip.changes.exclude(item_id=None).values("item_type", "item_id").annotate(last=Max("id"))
    return {(row["item_type"], row["item_id"]): row["last"] for row in rows}


def can_undo(change, latest):
    """Offer Undo / Restore for this change? (The POST re-checks against the current data.)"""
    if latest.get((change.item_type, change.item_id)) != change.pk or not change.before:
        return False
    if change.kind == TripChange.Kind.CHANGED:
        if change.item_type == "optiongroup" and change.before.get("before", {}).get("state", "open") != "open":
            return False  # undoing a reopen would need the pick again: pick it on the day
        return "after" in change.before and change.item_type in MODELS
    if change.kind == TripChange.Kind.REMOVED:
        return "object" in change.before and MODELS.get(change.item_type) in RESTORABLE
    return False


def undo(change):
    """Put a changed item's fields back. Saved normally, so it is recorded (and can be undone)."""
    model = MODELS.get(change.item_type)
    item = model.objects.filter(pk=change.item_id).first() if model else None
    if item is None:
        raise CannotUndo("That item no longer exists.")
    if latest_change_ids(change.trip).get((change.item_type, change.item_id)) != change.pk:
        raise CannotUndo("It has been changed again since; undo the newest change first.")
    fields = {f.attname: f for f in model._meta.concrete_fields}
    for attname, value in change.before["after"].items():
        if fields[attname].to_python(value) != getattr(item, attname):
            raise CannotUndo("It has been edited since, so undoing could lose that edit.")
    if isinstance(item, OptionGroup) and change.before["before"].get("state", "open") != "open":
        raise CannotUndo("Pick it again on its day.")
    for attname, value in change.before["before"].items():
        setattr(item, attname, fields[attname].to_python(value))
    if isinstance(item, OptionGroup) and item.state == OptionGroup.State.OPEN:
        item.decided_by, item.decided_at = None, None
    item.save()  # an open group's save clears its chosen option
    return item


def restore(change, actor=None):
    """Bring a removed leg, stay, activity, meal or section back with its links. A section of a type
    retired since (a phase, callout, free text or choose your adventure) comes back as a note."""
    from django.contrib.contenttypes.models import ContentType
    from django.core import serializers
    snap = change.before or {}
    data = snap.get("object")
    model = MODELS.get(change.item_type)
    if not data or model not in RESTORABLE:
        raise CannotUndo("That can't be restored.")
    if model.objects.filter(pk=data["pk"]).exists():
        raise CannotUndo("It's already back.")
    if not Trip.objects.filter(pk=change.trip_id, deleted_at=None).exists():
        raise CannotUndo("The trip is gone.")
    fields = dict(data["fields"])
    if model is Section:
        from .day_first import RETIRED, as_note
        if fields.get("section_type") in RETIRED:  # snapshotted before S2 retired its type: back as a note
            fields["title"], fields["content"] = as_note(fields["section_type"], fields.get("title"), fields.get("content"))
            fields["section_type"] = Section.Type.NOTE
    for field in model._meta.concrete_fields:
        if not field.is_relation or field.name not in fields or fields[field.name] is None:
            continue
        if field.related_model.objects.filter(pk=fields[field.name]).exists():
            continue
        if field.name in ("day", "trip"):
            raise CannotUndo(f"Its {field.name} was removed, so there's nowhere to put it back.")
        fields[field.name] = None  # e.g. a leg's travel section or a place that has gone
    with transaction.atomic(), quiet():
        loaded = next(serializers.deserialize("python", [{**data, "fields": fields}]))
        for name, ids in list(loaded.m2m_data.items()):
            related = model._meta.get_field(name).related_model
            loaded.m2m_data[name] = list(related.objects.filter(pk__in=ids).values_list("pk", flat=True))
        loaded.save()
        item = loaded.object
        content_type = ContentType.objects.get_for_model(model)
        for confirmation in Confirmation.objects.filter(pk__in=snap.get("links", []), trip_id=change.trip_id):
            ConfirmationLink.objects.get_or_create(confirmation=confirmation, content_type=content_type,
                                                   object_id=item.pk)
        for ref in snap.get("refs", []):
            source = ContentType.objects.get_for_id(ref["source_type_id"]).model_class()
            if source.objects.filter(pk=ref["source_id"], trip_id=change.trip_id).exists():
                ItemLink.objects.get_or_create(trip_id=change.trip_id, source_type_id=ref["source_type_id"],
                                               source_id=ref["source_id"], target_type=content_type,
                                               target_id=item.pk)
        # The to-dos that covered it, if they still exist (a pre-K1 snapshot keeps them as "tasks").
        task_ids = snap.get("task_links") or snap.get("tasks") or []
        if RESTORABLE.get(model) and task_ids:
            for task in BookingTask.objects.filter(pk__in=task_ids, trip_id=change.trip_id):
                task.link(item)
    _, label, trip_of, _ = TRACKED[model]
    record(change.trip_id, TripChange.Kind.ADDED, f"Restored {label(item)}", item, actor=actor,
           day_id=day_id_of(item))
    return item
