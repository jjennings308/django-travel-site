from django.apps import AppConfig


class BucketlistsConfig(AppConfig):
    name = 'apps.bucketlists'
    label = 'bucketlists'

    def ready(self):
        from . import signals  # noqa: F401  (bucket_list_count upkeep)
