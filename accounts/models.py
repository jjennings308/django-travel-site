from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model.

    Keep it close to Django's default, but gives us flexibility to add fields later
    (vendor flags, profile fields, etc.) without a painful migration.
    """
    # Example future-ready fields (optional; keep commented until you need them)
    # is_vendor = models.BooleanField(default=False)
    # timezone = models.CharField(max_length=64, default="America/New_York")

    pass
