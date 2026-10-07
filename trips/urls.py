"""URLs for the trips app.

Mounted at ``/trips/`` (config/urls.py). The two read views set the convention:
the list is the app root and a trip hangs off ``<pk>/``. The editing URLs
follow that, so a trip's edit page is a child of the trip rather than a
sibling of it.
"""

from django.urls import path

from . import views

app_name = "trips"

urlpatterns = [
    path("", views.trip_list, name="trip_list"),
    # The signed-in person's own profile. No pk: see the view.
    path("profile/", views.traveler_profile, name="traveler_profile"),
    # "new" cannot collide with "<int:pk>", so it needs no ordering care.
    path("new/", views.trip_create, name="trip_create"),
    path("<int:pk>/", views.trip_detail, name="trip_detail"),
    path("<int:pk>/edit/", views.trip_edit, name="trip_edit"),
    path("<int:pk>/delete/", views.trip_delete, name="trip_delete"),
    path("<int:pk>/restore/", views.trip_restore, name="trip_restore"),
    # A day is reached through its trip, so the trip's permission check runs
    # first and an unreachable trip is a 404 whatever the day.
    path("<int:trip_pk>/days/new/", views.day_create, name="day_create"),
    path("<int:trip_pk>/days/<int:pk>/", views.day_edit, name="day_edit"),
    path(
        "<int:trip_pk>/days/<int:pk>/delete/",
        views.day_delete,
        name="day_delete",
    ),
    # The section type is in the URL so "add a callout" is one link; it is still
    # validated against Section.Type inside the view.
    path(
        "<int:trip_pk>/days/<int:day_pk>/sections/new/<str:section_type>/",
        views.section_create,
        name="section_create",
    ),
    path(
        "<int:trip_pk>/days/<int:day_pk>/sections/<int:pk>/",
        views.section_edit,
        name="section_edit",
    ),
    path(
        "<int:trip_pk>/days/<int:day_pk>/sections/<int:pk>/delete/",
        views.section_delete,
        name="section_delete",
    ),
    # Comments hang off whatever they are about, so the URL names the kind of
    # target and its pk rather than a trip. "task" is the booking task; the view
    # maps every name to one model and 404s on an unknown one, so a hand-written
    # URL cannot name an arbitrary content type.
    path(
        "comments/<str:kind>/<int:pk>/",
        views.comment_create,
        name="comment_create",
    ),
    # A comment is edited and deleted by its own id, not by its target: editing
    # is a property of the comment ("is it mine?"), not of the page it sits on.
    path("comments/<int:pk>/edit/", views.comment_edit, name="comment_edit"),
]
