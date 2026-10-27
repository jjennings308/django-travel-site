"""The trip page offline (site roadmap R6): registered only on the trip page, per person."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.pwa import offline_cache_key
from apps.trips.models import Day, Trip, TripGrant, TripRole

User = get_user_model()


class OfflineTripPageTests(TestCase):
    def setUp(self):
        self.ed = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.vi = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Rome", start_date=date(2027, 5, 1), end_date=date(2027, 5, 3),
                                        created_by=self.ed)
        TripGrant.objects.create(trip=self.trip, user=self.ed, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.vi, role=TripRole.VIEWER)
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 5, 1))

    def html(self, url, user):
        self.client.force_login(user)
        return self.client.get(url).content.decode()

    def test_trip_page_registers_with_this_persons_key(self):
        html = self.html(reverse("trips:trip_detail", args=[self.trip.pk]), self.vi)
        self.assertIn(f'register("/sw.js?u={offline_cache_key(self.vi)}', html)
        self.assertIn('scope: "/trips/"', html)
        self.assertIn(f'"sbl-offline-v2-{offline_cache_key(self.vi)}"', html)  # the worker's cache name (sw.js)
        self.assertIn("data-offline-save", html)  # Save for offline, for a viewer too
        self.assertIn("data-sbl-offline hidden", html)  # the banner, off until served offline
        self.assertNotIn(offline_cache_key(self.ed), html)

    def test_not_registered_on_other_trip_pages(self):
        for url in (reverse("trips:trip_settings", args=[self.trip.pk]), reverse("trips:trip_list"),
                    reverse("trips:day_edit", args=[self.trip.pk, self.day.pk]),
                    reverse("trips:trip_people", args=[self.trip.pk])):
            with self.subTest(url=url):
                self.assertNotIn("/sw.js", self.html(url, self.ed))
