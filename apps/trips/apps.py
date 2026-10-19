from django.apps import AppConfig


class TripsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.trips"
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
        from . import changes  # noqa: F401  (change records for the digest, site roadmap R7)
        # Ticket files count towards the account's storage limit (R15).
        from django.db.models import Sum
        from apps.media_app import quota
        from .models import ConfirmationFile

        def tickets(user):
            return ConfirmationFile.objects.filter(uploaded_by=user).aggregate(total=Sum("size"))["total"] or 0
        quota.register(tickets)
