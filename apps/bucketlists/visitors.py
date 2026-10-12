# bucketlists/visitors.py
"""``visitor_count`` on places, cities, regions and countries: how many members
have been there.

A member has been to a city when they ticked off a bucket-list goal located there
(the goal's city, its event's or activity's city, its places' cities) or were a
traveller (with an account) on a finished trip naming the city (``Trip.cities`` or
a day's city). A region or country counts members who've been to any of its
cities, plus country-only goals; a place (POI) counts completed goals naming it
or whose event was held there. Each member counts once per place.

Lives in bucketlists because it reads goals *and* trips (locations may import
neither). ``recount()`` recomputes everything in a few grouped queries and writes
only the counts that changed; signals call it when a goal or trip changes, and
``manage.py recount_visitors`` runs it nightly for trips that finished by date.
"""
from collections import defaultdict

from django.utils import timezone

from apps.locations.models import POI, City, Country, Region
from apps.trips.models import Trip

from .models import BucketListItem


def _visitors():
    """({city_id: {user_ids}}, {poi_id: {user_ids}}, {country_id: {user_ids}} for country-only goals)."""
    city, poi, country = defaultdict(set), defaultdict(set), defaultdict(set)
    for row in BucketListItem.objects.filter(status="completed").values(
            "user_id", "city_id", "activity__city_id", "activity__country_id", "event__city_id",
            "event__country_id", "event__poi_id", "event__poi__city_id", "pois__id", "pois__city_id"):
        user = row["user_id"]
        cities = {row["city_id"], row["activity__city_id"], row["event__city_id"], row["pois__city_id"],
                  row["event__poi__city_id"]} - {None}
        for c in cities:
            city[c].add(user)
        for p in {row["pois__id"], row["event__poi_id"]} - {None}:
            poi[p].add(user)
        if not cities:  # a goal known only by its country (activity or typed-town event)
            for c in {row["activity__country_id"], row["event__country_id"]} - {None}:
                country[c].add(user)
    finished = Trip.objects.live().filter(end_date__lt=timezone.localdate())
    for field in ("cities__id", "days__city_id"):
        for row in finished.filter(travelers__user__isnull=False).values("travelers__user_id", field):
            if row[field]:
                city[row[field]].add(row["travelers__user_id"])
    return city, poi, country


def _store(model, counts):
    """Write the new counts (0 for anything not in ``counts``); only changed rows."""
    changed = []
    for obj in model.objects.only("pk", "visitor_count"):
        new = counts.get(obj.pk, 0)
        if obj.visitor_count != new:
            obj.visitor_count = new
            changed.append(obj)
    model.objects.bulk_update(changed, ["visitor_count"], batch_size=500)
    return len(changed)


def recount():
    """Recompute visitor_count everywhere; returns how many rows changed."""
    city_users, poi_users, country_only = _visitors()
    region_users, country_users = defaultdict(set), defaultdict(set)
    for city_id, region_id, country_id in City.objects.filter(pk__in=city_users).values_list("pk", "region_id", "country_id"):
        if region_id:
            region_users[region_id] |= city_users[city_id]
        country_users[country_id] |= city_users[city_id]
    for country_id, users in country_only.items():
        country_users[country_id] |= users
    return sum(_store(model, {pk: len(users) for pk, users in data.items()}) for model, data in (
        (City, city_users), (POI, poi_users), (Region, region_users), (Country, country_users)))
