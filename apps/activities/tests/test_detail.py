"""The activity page shows the activity's own information (it was a copy of the
country page): where, when, details; no country-only sections."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus


class ActivityDetailTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("u", "u@example.com", "pw-1234-abcd")
        self.activity = Activity.objects.create(
            category=ActivityCategory.objects.get(name="Festival"), name="Oktoberfest", description="Beer and music",
            suggested_location="Munich, Germany", suggested_timeframe="October 2027", created_by=user,
            visibility="public", approval_status=ApprovalStatus.APPROVED, booking_required=True)
        self.client.force_login(user)

    def test_shows_where_and_when(self):
        page = self.client.get(reverse("activities:activity_detail", args=[self.activity.slug]))
        for text in ("Munich, Germany", "October 2027", "Festival", "Beer and music", "Booking required"):
            self.assertContains(page, text)
        for text in ("ISO Codes", "Major Cities", "Top Attractions"):
            self.assertNotContains(page, text)
