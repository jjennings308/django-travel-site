# core/signals.py
from django.db.models.signals import pre_save
from django.dispatch import receiver

from .utils.images import convert_heic_uploads


@receiver(pre_save, dispatch_uid="core_convert_heic_uploads")
def convert_heic_before_save(sender, instance, raw=False, **kwargs):
    """Every model: store a newly uploaded HEIC image as JPEG (see utils.images)."""
    if not raw:
        convert_heic_uploads(instance)
