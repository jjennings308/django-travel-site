# bucketlists/signals.py
"""Keep Activity.bucket_list_count and Event.bucket_list_count in step with the
bucket-list items that point at them (recounted, so they can't drift)."""
from django.db import transaction
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import receiver

from apps.trips.models import Day, Trip

from .models import BucketListItem


KINDS = ("activity", "event")


def _recount(kind, target_id):
    if target_id:
        model = BucketListItem._meta.get_field(kind).related_model
        count = BucketListItem.objects.filter(**{f"{kind}_id": target_id}).count()
        model.objects.filter(pk=target_id).update(bucket_list_count=count)


@receiver(pre_save, sender=BucketListItem)
def remember_old_targets(sender, instance, raw=False, **kwargs):
    """An item can gain or change its activity/event after creation (linking a goal,
    picking a date), so the old ones need recounting too."""
    old = None
    if instance.pk and not raw:
        old = BucketListItem.objects.filter(pk=instance.pk).values("status", *(f"{k}_id" for k in KINDS)).first()
    instance._old_targets = old or {}


@receiver(post_save, sender=BucketListItem)
def item_saved(sender, instance, raw=False, **kwargs):
    if raw:
        return
    old = getattr(instance, "_old_targets", {})
    for kind in KINDS:
        new_id = getattr(instance, f"{kind}_id")
        _recount(kind, new_id)
        if old.get(f"{kind}_id") not in (None, new_id):
            _recount(kind, old[f"{kind}_id"])


@receiver(post_save, sender=BucketListItem, dispatch_uid="bucketlists_award_badges")
def award_badges_after_save(sender, instance, raw=False, **kwargs):
    """Goals added, ticked off, dated or put on a trip can earn badges."""
    if not raw:
        from .badges import award_badges
        award_badges(instance.user)


@receiver(post_delete, sender=BucketListItem)
def item_deleted(sender, instance, **kwargs):
    for kind in KINDS:
        _recount(kind, getattr(instance, f"{kind}_id"))


# ---- visitor counts on places (see visitors.py) ------------------------------------
def _run_recount():
    from .visitors import recount
    recount()


def _recount_visitors():
    """After the transaction commits, once: several goal/trip saves in one request
    queue a single recount, and it never reads half-written data. (Outside a
    transaction on_commit runs at once.) No state is kept between transactions."""
    connection = transaction.get_connection()
    if any(func is _run_recount for _, func, *_ in connection.run_on_commit):
        return
    transaction.on_commit(_run_recount)


@receiver(post_save, sender=BucketListItem, dispatch_uid="bucketlists_visitors_item_saved")
def visitors_after_goal_saved(sender, instance, raw=False, **kwargs):
    was_done = getattr(instance, "_old_targets", {}).get("status") == "completed"
    if not raw and (instance.status == "completed" or was_done):
        _recount_visitors()


@receiver(post_delete, sender=BucketListItem, dispatch_uid="bucketlists_visitors_item_deleted")
def visitors_after_goal_deleted(sender, instance, **kwargs):
    if instance.status == "completed":
        _recount_visitors()


@receiver(m2m_changed, sender=BucketListItem.pois.through, dispatch_uid="bucketlists_visitors_item_pois")
def visitors_after_goal_places_changed(sender, instance, action, **kwargs):
    if action.startswith("post_") and isinstance(instance, BucketListItem) and instance.status == "completed":
        _recount_visitors()


def _finished(trip):
    """Whether ``trip`` is over. Its end date can still be the string it was created
    with (importers, tests) until the row is re-read, so parse it rather than compare."""
    if trip is None or trip.end_date is None:
        return False
    from datetime import date
    from django.utils import timezone
    from django.utils.dateparse import parse_date
    end = trip.end_date if isinstance(trip.end_date, date) else parse_date(str(trip.end_date))
    return end is not None and end < timezone.localdate()


@receiver(post_save, sender=Trip, dispatch_uid="bucketlists_visitors_trip_saved")
def visitors_after_trip_saved(sender, instance, raw=False, **kwargs):
    if not raw and _finished(instance):
        _recount_visitors()


@receiver(post_save, sender=Day, dispatch_uid="bucketlists_visitors_day_saved")
@receiver(post_delete, sender=Day, dispatch_uid="bucketlists_visitors_day_deleted")
def visitors_after_day_changed(sender, instance, raw=False, **kwargs):
    if not raw and _finished(instance.trip):
        _recount_visitors()


@receiver(m2m_changed, sender=Trip.cities.through, dispatch_uid="bucketlists_visitors_trip_cities")
@receiver(m2m_changed, sender=Trip.travelers.through, dispatch_uid="bucketlists_visitors_trip_travelers")
def visitors_after_trip_people_or_places(sender, instance, action, **kwargs):
    if action.startswith("post_") and isinstance(instance, Trip) and _finished(instance):
        _recount_visitors()


# --- Reviews: "Been there" when the reviewer has ticked the item off ------------------------------
# Here rather than in reviews, because reviews may not import bucketlists.
from apps.reviews.models import Review  # noqa: E402


@receiver(pre_save, sender=Review, dispatch_uid="bucketlists_review_been_there")
def mark_review_been_there(sender, instance, raw=False, **kwargs):
    if raw or instance.is_verified_visit or instance.user_id is None:
        return
    done = BucketListItem.objects.filter(user_id=instance.user_id, status="completed")
    lookups = {"activity_id": "activity_id", "event_id": "event_id", "location_id": "city_id", "poi_id": "pois"}
    for field, lookup in lookups.items():
        value = getattr(instance, field)
        if value and done.filter(**{lookup: value}).exists():
            instance.is_verified_visit = True
            return
