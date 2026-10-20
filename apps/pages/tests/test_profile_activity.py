"""The profile page's Recent activity (apps/pages/activity_feed.py)."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.bucketlists.models import BucketListItem
from apps.locations.models import POI, City, Country
from apps.reviews.models import Review
from apps.trips.models import Traveler, Trip

User = get_user_model()
APPROVED = {"approval_status": ApprovalStatus.APPROVED}


class ProfileActivityTests(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada", "ada@example.com", "pw-1234-abcd")
        self.other = User.objects.create_user("bob", "bob@example.com", "pw-1234-abcd")
        country = Country.objects.create(name="Testland", slug="testland", iso_code="TL", iso3_code="TLD",
                                         continent="Europe", **APPROVED)
        self.city = City.objects.create(name="Testville", slug="testville", country=country, latitude=1,
                                        longitude=1, **APPROVED)
        BucketListItem.objects.create(user=self.ada, custom_title="Public dream", is_public=True)
        BucketListItem.objects.create(user=self.ada, custom_title="Secret dream")
        done = BucketListItem.objects.create(user=self.ada, city=self.city, is_public=True)
        done.complete()
        self.place = POI.objects.create(name="Old Mill", slug="old-mill", city=self.city, latitude=1, longitude=1,
                                        submitted_by=self.ada, **APPROVED)
        POI.objects.create(name="Pending Shed", slug="shed", city=self.city, latitude=1, longitude=1,
                           submitted_by=self.ada)
        Review.objects.create(user=self.ada, review_type="poi", poi=self.place, rating=4, comment="Nice",
                              is_approved=True)
        trip = Trip.objects.create(name="Spring trip", start_date=date.today() - timedelta(days=9),
                                   end_date=date.today() - timedelta(days=2))
        trip.travelers.add(Traveler.objects.get(user=self.ada))
        User.objects.filter(pk=self.ada.pk).update(profile_visibility="public")

    def feed(self, viewer=None):
        self.client.logout()
        if viewer:
            self.client.force_login(viewer)
        return self.client.get(reverse("pages:profile_activity", args=["ada"]))

    def test_owner_sees_everything_others_only_public(self):
        own = self.feed(self.ada)
        for text in ("Public dream", "Secret dream", "Ticked off", "Testville", "Old Mill", "Reviewed (4★)",
                     "Spring trip", "Only you"):
            self.assertContains(own, text)
        self.assertNotContains(own, "Pending Shed")
        for viewer in (self.other, None):
            public = self.feed(viewer)
            self.assertContains(public, "Public dream")
            self.assertContains(public, "Old Mill")
            for hidden in ("Secret dream", "Spring trip", "Only you", "Pending Shed"):
                self.assertNotContains(public, hidden)

    def test_private_profile_is_owner_only(self):
        User.objects.filter(pk=self.ada.pk).update(profile_visibility="private")
        self.assertEqual(self.feed(self.other).status_code, 404)
        self.assertEqual(self.feed(self.ada).status_code, 200)

    def test_same_day_runs_fold_into_one_line(self):
        for n in range(4):
            POI.objects.create(name=f"Spot {n}", slug=f"spot-{n}", city=self.city, latitude=1, longitude=1,
                               submitted_by=self.ada, **APPROVED)
        page = self.feed(self.ada).content.decode()
        self.assertIn("Added 5 places:", page)  # Old Mill + 4 spots, all today
        self.assertEqual(page.count("Added the place"), 0)

    def test_profile_page_loads_it_and_the_placeholder_is_gone(self):
        self.client.force_login(self.ada)
        page = self.client.get(reverse("profile"))
        self.assertContains(page, reverse("pages:profile_activity", args=["ada"]))
        self.assertNotContains(page, "coming soon")
