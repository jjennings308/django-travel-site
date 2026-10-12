from django.apps import AppConfig


class ReviewsConfig(AppConfig):
    name = 'apps.reviews'
    label = 'reviews'

    def ready(self):
        from . import signals  # noqa: F401  (rating upkeep)
