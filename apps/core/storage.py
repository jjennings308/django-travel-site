# core/storage.py
"""Private file storage: files kept outside MEDIA_ROOT, so nginx's /media/ never
serves them. They have no public URL; a view checks who may download each one."""
import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateStorage(FileSystemStorage):
    """FileSystemStorage rooted at settings.PRIVATE_MEDIA_ROOT, read on each use
    (not cached), so the setting can be overridden (tests, other deployments)."""

    @property
    def base_location(self):
        return self._value_or_setting(self._location, settings.PRIVATE_MEDIA_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def url(self, name):
        raise ValueError("Private files have no public URL; serve them through a view that checks access.")


def private_storage():
    """Callable for FileField(storage=...)."""
    return PrivateStorage()
