"""The dashboard's first-run welcome (site roadmap R14)."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.bucketlists.models import BucketListItem
from apps.trips.models import Trip, TripGrant

User = get_user_model()


class WelcomeTests(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada", "ada@example.com", "pw-1234-abcd")
        self.client.force_login(self.ada)

    def steps(self):
        return self.client.get(reverse("pages:dashboard")).context["welcome"]

    def test_steps_tick_off(self):
        self.assertEqual([s["done"] for s in self.steps()], [False, False, False])
        BucketListItem.objects.create(user=self.ada, custom_title="See the Alps")
        trip = Trip.objects.create(name="Alps", start_date=date(2027, 7, 1), end_date=date(2027, 7, 5),
                                   created_by=self.ada)
        TripGrant.objects.create(trip=trip, user=self.ada, role="editor")
        self.assertEqual([s["done"] for s in self.steps()], [True, True, False])
        bob = User.objects.create_user("bob", "bob@example.com", "pw-1234-abcd")
        TripGrant.objects.create(trip=trip, user=bob, role="viewer")
        self.assertIsNone(self.steps())  # all done: the card goes

    def test_hide_this(self):
        page = self.client.get(reverse("pages:dashboard"))
        self.assertContains(page, 'id="welcome"')
        self.client.post(reverse("pages:welcome_dismiss"))
        self.assertNotContains(self.client.get(reverse("pages:dashboard")), 'id="welcome"')

    def test_trip_list_empty_state_offers_to_start(self):
        page = self.client.get(reverse("trips:trip_list"))
        self.assertContains(page, reverse("trips:trip_create"))
        self.assertContains(page, "Start a trip")
