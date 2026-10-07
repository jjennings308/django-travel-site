from django.apps import AppConfig


class TripsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "trips"
    # Pinned deliberately. Without this the label would become "trips" only by
    # luck of Django's last-component rule; stating it means the database
    # tables (trips_trip, trips_day, ...) and the recorded migration history
    # keep matching even if the package is ever moved again.
    label = "trips"
    verbose_name = "Trips"

    def ready(self):
        # Importing registers the post_save receivers that keep Traveler and
        # auth.User linked; see trips/signals.py.
        from . import signals  # noqa: F401
