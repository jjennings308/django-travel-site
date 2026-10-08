from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'apps.core'
    label = 'core'

    def ready(self):
        # Let Pillow open HEIC/HEIF photos (iPhone default), so ImageField uploads
        # validate and images can be read/converted like any other format.
        from pillow_heif import register_heif_opener
        register_heif_opener()

        from . import signals  # noqa: F401  (HEIC uploads are stored as JPEG)
