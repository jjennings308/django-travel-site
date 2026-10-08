# bucketlists/signals.py
"""Keep Activity.bucket_list_count and Event.bucket_list_count in step with the
bucket-list items that point at them (recounted, so they can't drift)."""
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

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
        old = BucketListItem.objects.filter(pk=instance.pk).values(*(f"{k}_id" for k in KINDS)).first()
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


@receiver(post_delete, sender=BucketListItem)
def item_deleted(sender, instance, **kwargs):
    for kind in KINDS:
        _recount(kind, getattr(instance, f"{kind}_id"))
