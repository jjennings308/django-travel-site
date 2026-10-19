"""Rating a finished trip's places (site roadmap R17): the answers become catalogue reviews.

``targets(trip)`` — the published catalogue items the trip itself knows: its cities (the trip's, its
days', its stays') and the places its activities are linked to. (Meals and day plans join in R18.)
``ask(today)`` — everyone with access to a trip that ended (yesterday back to ``ASK_WITHIN_DAYS``) gets
one ``trip_rating`` notification, once ever (``TripRatingPrompt``); ``send_trip_digests`` triggers it daily
through ``trips.signals.daily_run``.
``save(trip, user, answers)`` — upserts their reviews (``reviews.services``); "Been there" only for
people on the trip's traveller roster.
"""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.trips.models import Day, Lodging, Trip, TripActivity, TripGrant

from . import services as reviews
from .models import TripRatingPrompt

ASK_WITHIN_DAYS = 30


def targets(trip):
    """[(kind, item)] in a stable order: cities, then places."""
    city_ids = set(trip.cities.values_list("pk", flat=True))
    city_ids |= set(Day.objects.filter(trip=trip).exclude(city=None).values_list("city_id", flat=True))
    city_ids |= set(Lodging.objects.filter(trip=trip).exclude(city=None).values_list("city_id", flat=True))
    cities = reviews.public("city").filter(pk__in=city_ids).order_by("name")
    poi_ids = TripActivity.objects.filter(trip=trip).exclude(poi=None).values_list("poi_id", flat=True)
    places = reviews.public("poi").filter(pk__in=poi_ids).order_by("name")
    return [("city", c) for c in cities] + [("poi", p) for p in places]


def ask(today=None):
    """Send the rating prompts that are due. Returns how many were sent."""
    from apps.notifications.services import notify
    today = today or timezone.localdate()
    trips = Trip.objects.filter(deleted_at=None, end_date__lt=today,
                                end_date__gte=today - timedelta(days=ASK_WITHIN_DAYS))
    sent = 0
    for trip in trips:
        if not targets(trip):
            continue
        asked = set(TripRatingPrompt.objects.filter(trip=trip).values_list("user_id", flat=True))
        for grant in TripGrant.objects.filter(trip=trip, user__is_active=True).select_related("user"):
            if grant.user_id in asked:
                continue
            TripRatingPrompt.objects.create(trip=trip, user=grant.user)
            notify(grant.user, "trip_rating", f"How was “{trip.name}”?",
                   f"“{trip.name}” has finished. Rate the places you went, in a minute: your ratings help "
                   "other members, and you can skip it.", reverse("reviews:trip_rate", args=[trip.pk]), obj=trip)
            sent += 1
    return sent


def was_there(trip, user):
    return trip.travelers.filter(user=user).exists()


def save(trip, user, answers):
    """``answers``: {(kind, pk): (rating 1–5, comment)}. Upserts reviews; returns how many."""
    allowed = {(kind, item.pk): item for kind, item in targets(trip)}
    verified = was_there(trip, user)
    saved = 0
    for key, (rating, comment) in answers.items():
        item = allowed.get(key)
        if item is None or not rating:
            continue
        reviews.upsert_review(user, item, rating, comment, visit_date=trip.start_date, verified=verified)
        saved += 1
    TripRatingPrompt.objects.update_or_create(trip=trip, user=user, defaults={"answered_at": timezone.now()})
    return saved


def skip(trip, user):
    TripRatingPrompt.objects.update_or_create(trip=trip, user=user, defaults={"skipped_at": timezone.now()})
