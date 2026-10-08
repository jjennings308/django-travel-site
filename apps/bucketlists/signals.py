# bucketlists/signals.py
"""Keep Activity.bucket_list_count and Event.bucket_list_count in step with the
bucket-list items that point at them (recounted, so they can't drift)."""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import BucketListItem


def _recount(item):
    for kind in ("activity", "event"):
        target_id = getattr(item, f"{kind}_id")
        if target_id:
            model = BucketListItem._meta.get_field(kind).related_model
            count = BucketListItem.objects.filter(**{f"{kind}_id": target_id}).count()
            model.objects.filter(pk=target_id).update(bucket_list_count=count)


@receiver(post_save, sender=BucketListItem)
def item_saved(sender, instance, created, **kwargs):
    if created:
        _recount(instance)


@receiver(post_delete, sender=BucketListItem)
def item_deleted(sender, instance, **kwargs):
    _recount(instance)
