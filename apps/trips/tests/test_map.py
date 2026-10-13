"""The trip map: day cities in order (repeats merged), other trip cities, access as the trip."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import City, Country
from apps.trips.models import Day, Trip, TripGrant, TripRole

User = get_user_model()


class TripMapTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.stranger = User.objects.create_user("st", "st@example.com", "pw-1234-abcd")
        us = Country.objects.create(name="United States", slug="us", iso_code="US", iso3_code="USA",
                                    continent="North America", approval_status=ApprovalStatus.APPROVED)
        self.city = {n: City.objects.create(name=n, slug=n.lower(), country=us, latitude=lat, longitude=lng,
                                            approval_status=ApprovalStatus.APPROVED)
                     for n, lat, lng in (("Denver", 39.7, -105.0), ("Moab", 38.6, -109.5), ("Taos", 36.4, -105.6))}
        self.trip = Trip.objects.create(name="Southwest", start_date=date(2027, 5, 1), end_date=date(2027, 5, 5),
                                        created_by=self.user)
        TripGrant.objects.create(trip=self.trip, user=self.user, role=TripRole.VIEWER)
        self.trip.cities.set(self.city.values())
        for n, (d, c) in enumerate([(1, "Denver"), (2, "Moab"), (3, "Moab"), (4, "Denver")], start=1):
            Day.objects.create(trip=self.trip, date=date(2027, 5, d), day_number=n, city=self.city[c])
        self.client.force_login(self.user)

    def test_stops_in_day_order_with_repeats_merged(self):
        data = self.client.get(reverse("trips:trip_map_data", args=[self.trip.pk])).json()
        stops = [(f["properties"].get("order"), f["properties"]["name"]) for f in data["features"]]
        self.assertEqual(stops, [(1, "Denver"), (2, "Moab"), (3, "Denver"), (None, "Taos")])
        self.assertIn("May 2 – May 3 · 2 days", data["features"][1]["properties"]["subtitle"])

    def test_page_and_header_link(self):
        page = self.client.get(reverse("trips:trip_map", args=[self.trip.pk]))
        self.assertContains(page, reverse("trips:trip_map_data", args=[self.trip.pk]))
        self.assertContains(page, 'data-route="1"')
        self.assertContains(self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])),
                            reverse("trips:trip_map", args=[self.trip.pk]))

    def test_no_grant_is_404_and_public_view_has_no_map(self):
        self.client.force_login(self.stranger)
        for name in ("trips:trip_map", "trips:trip_map_data"):
            self.assertEqual(self.client.get(reverse(name, args=[self.trip.pk])).status_code, 404)
        self.trip.enable_public()
        self.client.logout()
        public = self.client.get(reverse("public_trip", args=[self.trip.public_token]))
        self.assertNotContains(public, "data-sbl-map")
        self.assertNotContains(public, reverse("trips:trip_map_data", args=[self.trip.pk]))

    def test_empty_trip_says_how_to_add_places(self):
        empty = Trip.objects.create(name="Blank", start_date=date(2027, 6, 1), end_date=date(2027, 6, 2), created_by=self.user)
        TripGrant.objects.create(trip=empty, user=self.user, role=TripRole.EDITOR)
        page = self.client.get(reverse("trips:trip_map", args=[empty.pk]))
        self.assertNotContains(page, "data-sbl-map")
        self.assertContains(page, "No places on this trip yet")
