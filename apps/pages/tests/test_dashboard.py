"""Home (ux-consistency V5): the greeting as the page header, three cards — next trip, bucket list, needs you — with
and without data, no Recent activity or Quick Access, and a fixed number of queries."""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.bucketlists.models import BucketListItem
from apps.reviews.models import TripRatingPrompt
from apps.trips.models import BookingTask, Trip, TripGrant, TripRole

URL = reverse("pages:dashboard")


def card(html, name):
    start = html.index(f'data-home-card="{name}"')
    return html[start : html.index("</section>", start)]


class Fixture(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ada", "ada@example.com", "pw-1234-abcd", first_name="Ada")
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def page(self):
        return self.client.get(URL).content.decode()

    def trip(self, name, start, nights=3, **extra):
        trip = Trip.objects.create(
            name=name, start_date=start, end_date=start + timedelta(days=nights), created_by=self.user, **extra
        )
        TripGrant.objects.create(trip=trip, user=self.user, role=TripRole.EDITOR)
        return trip

    def fill(self):
        """A bit of everything the three cards show."""
        soon = self.trip("Lisbon", self.today + timedelta(days=12))
        self.trip("Kyoto", self.today + timedelta(days=90))
        BookingTask.objects.create(trip=soon, title="Book the tram tour", priority=BookingTask.Priority.HIGH)
        BookingTask.objects.create(trip=soon, title="Book the hotel", done=True)
        BucketListItem.objects.create(user=self.user, custom_title="See the northern lights")
        BucketListItem.objects.create(user=self.user, custom_title="Climb Kilimanjaro", status="completed")
        past = self.trip("Rome", self.today - timedelta(days=10), nights=4)
        TripRatingPrompt.objects.create(trip=past, user=self.user)
        Activity.objects.create(
            name="Fado night",
            description="Music",
            category=ActivityCategory.objects.first(),
            created_by=self.user,
            approval_status=ApprovalStatus.CHANGES_REQUESTED,
            reviewed_at=timezone.now(),
        )


class EmptyHomeTests(Fixture):
    def test_greeting_header_and_actions(self):
        html = self.page()
        self.assertRegex(html, r'<h1 class="sbl-page-title">Good (morning|afternoon|evening), Ada')
        self.assertIn('data-home-action="goal"', html)
        self.assertIn('data-home-action="trip"', html)
        for gone in ("Quick Access", "Recent activity", "Recent Activity", "Welcome back", "bg-gradient-to-br"):
            self.assertNotIn(gone, html)

    def test_each_card_says_what_to_do_when_empty(self):
        html = self.page()
        self.assertIn("No trip coming up", card(html, "next-trip"))
        self.assertIn("Your bucket list is empty", card(html, "bucket"))
        self.assertIn("Nothing needs you", card(html, "needs-you"))

    def test_no_staff_links_for_members(self):
        self.assertNotIn("data-staff-links", self.page())


class FullHomeTests(Fixture):
    def setUp(self):
        super().setUp()
        self.fill()

    def test_next_trip(self):
        trip = card(self.page(), "next-trip")
        self.assertIn("Lisbon", trip)
        self.assertNotIn("Rome", trip)  # over
        self.assertIn("In 12 days", trip)
        self.assertIn("1 of 2", trip)  # to-dos done
        self.assertIn("1 more coming up", trip)

    def test_a_trip_under_way(self):
        Trip.objects.filter(name="Lisbon").update(start_date=self.today - timedelta(days=1))
        self.assertIn("Happening now · day 2", card(self.page(), "next-trip"))

    def test_bucket_list(self):
        bucket = card(self.page(), "bucket")
        self.assertIn("1 of 2", bucket)
        self.assertIn("See the northern lights", bucket)
        self.assertNotIn("Climb Kilimanjaro", bucket)  # done goals aren't listed

    def test_needs_you(self):
        needs = card(self.page(), "needs-you")
        self.assertIn("Book the tram tour", needs)
        self.assertNotIn("Book the hotel", needs)  # done
        self.assertIn(reverse("reviews:trip_rate", args=[Trip.objects.get(name="Rome").pk]), needs)
        self.assertIn("Fado night", needs)
        self.assertIn("Changes requested", needs)

    def test_answered_ratings_and_old_decisions_drop_off(self):
        TripRatingPrompt.objects.update(answered_at=timezone.now())
        Activity.objects.update(reviewed_at=timezone.now() - timedelta(days=200))
        needs = card(self.page(), "needs-you")
        self.assertNotIn("Rate the places", needs)
        self.assertNotIn("Fado night", needs)

    def test_staff_get_a_row_of_links(self):
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save()
        html = self.page()
        self.assertIn("data-staff-links", html)
        self.assertIn(reverse("pages:staff_dashboard"), html)

    def test_recommendation_reasons_use_one_badge(self):
        self.assertNotRegex(self.page(), r"bg-(emerald|fuchsia|sky)-500 text-white")


class QueryCountTests(Fixture):
    def test_fixed_whatever_the_member_has(self):
        self.client.get(URL)  # warm caches (content types, the catalogue counts)
        with CaptureQueriesContext(connection) as empty:
            self.client.get(URL)
        self.fill()
        for n in range(3):
            BucketListItem.objects.create(user=self.user, custom_title=f"Goal {n}", target_date=date(2030, 1, 1))
        with CaptureQueriesContext(connection) as full:
            self.client.get(URL)
        # 30 with nothing (session, user, middleware, the cards' counts, recommendations, badges); with data the cards
        # add the next trip's cities and "more coming up", and the open goals with their places: never one per item.
        self.assertEqual(len(empty), 30)
        self.assertEqual(len(full), 34)
