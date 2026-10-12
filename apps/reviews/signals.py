# reviews/signals.py
"""Keep the reviewed item's average_rating / review_count in step with its visible reviews."""
from django.core.exceptions import ObjectDoesNotExist
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Review
from .services import recount


@receiver(post_save, sender=Review, dispatch_uid="reviews_recount_saved")
@receiver(post_delete, sender=Review, dispatch_uid="reviews_recount_deleted")
def recount_target(sender, instance, raw=False, **kwargs):
    if raw:
        return
    try:
        target = instance.target
    except ObjectDoesNotExist:  # the item itself is being deleted
        return
    if target is not None:
        recount(target)
