"""The trip calendar page and feed (site roadmap R4); the feed is built in ``calendar.py``.

``trips:trip_calendar`` — anyone who can see the trip gets their own private link (made on the
first visit), how to subscribe, and Reset. ``trips:trip_calendar_feed`` — what calendar apps fetch;
they can't log in, so the token is the key, and the owner's access is checked on every fetch.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from . import calendar
from .models import Trip, TripCalendarToken


def _trip(request, pk):
    return get_object_or_404(Trip.objects.visible_to(request.user), pk=pk)


@login_required
def trip_calendar(request, pk):
    trip = _trip(request, pk)
    token = TripCalendarToken.for_user(trip, request.user)
    feed = request.build_absolute_uri(reverse("trips:trip_calendar_feed", args=[token.token]))
    return render(request, "trips/trip_calendar.html", {
        "trip": trip, "feed_url": feed, "mine_url": f"{feed}?mine=1",
        "webcal_url": feed.replace("https://", "webcal://").replace("http://", "webcal://"),
    })


@login_required
@require_POST
def trip_calendar_reset(request, pk):
    trip = _trip(request, pk)
    TripCalendarToken.for_user(trip, request.user).reset()
    messages.success(request, "Your calendar link was reset. The old one stops working; subscribe again with the new one.")
    return redirect("trips:trip_calendar", pk=trip.pk)


@never_cache
def trip_calendar_feed(request, token):
    found = (TripCalendarToken.objects.select_related("trip", "user")
             .filter(token=token, revoked_at=None, trip__deleted_at=None).first())
    if found is None or not found.user.is_active or not found.trip.can(found.user, "view"):
        raise Http404
    body = calendar.build(found.trip, viewer=found.user, mine=request.GET.get("mine") == "1")
    response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = 'inline; filename="trip.ics"'
    return response
