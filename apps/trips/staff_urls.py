"""Staff-only trips URLs, mounted under ``/staff/trips/`` (config/urls.py).

Kept out of ``trips.urls`` so the staff pages sit beside the rest of ``/staff/``
rather than inside the signed-in traveler's ``/trips/`` space.
"""

from django.urls import path

from . import views

app_name = "trips_staff"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
]
