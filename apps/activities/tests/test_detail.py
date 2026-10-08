"""The activity page shows the activity's own information: where (linked to the
catalogue), how often it happens and details. Its dates (events) are tested in
apps.events, since activities may not import events."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.activities.forms import ActivityEditForm
from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.locations.models import City, Country, Region


class ActivityPlaceFixture(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("u", "u@example.com", "pw-1234-abcd")
        self.germany = Country.objects.create(name="Germany", slug="germany", iso_code="DE", iso3_code="DEU",
                                              continent="Europe", approval_status=ApprovalStatus.APPROVED)
        self.france = Country.objects.create(name="France", slug="france", iso_code="FR", iso3_code="FRA",
                                             continent="Europe", approval_status=ApprovalStatus.APPROVED)
        self.bavaria = Region.objects.create(country=self.germany, name="Bavaria", slug="bavaria")
        self.munich = City.objects.create(name="Munich", slug="munich", country=self.germany, region=self.bavaria,
                                          latitude=48, longitude=11, approval_status=ApprovalStatus.APPROVED)
        self.festival = ActivityCategory.objects.get(name="Festival")
        self.activity = Activity.objects.create(
            category=self.festival, name="Oktoberfest", description="Beer and music", city=self.munich,
            recurrence="yearly", usual_months=[9, 10], created_by=self.user,
            visibility="public", approval_status=ApprovalStatus.APPROVED, booking_required=True)
        self.client.force_login(self.user)


class ActivityDetailTests(ActivityPlaceFixture):
    def test_city_fills_region_and_country(self):
        self.assertEqual((self.activity.region, self.activity.country), (self.bavaria, self.germany))
        self.assertEqual(self.activity.place_name, "Munich, Bavaria, Germany")

    def test_shows_place_recurrence_and_details(self):
        page = self.client.get(reverse("activities:activity_detail", args=[self.activity.slug]))
        for text in ("Every year", "September, October", "Festival", "Beer and music", "Booking required",
                     reverse("locations:city_detail", args=["munich"]), reverse("locations:region_detail", args=["bavaria"])):
            self.assertContains(page, text)
        for text in ("ISO Codes", "Major Cities", "Top Attractions"):
            self.assertNotContains(page, text)


class ActivityFormPlaceTests(ActivityPlaceFixture):
    def data(self, **over):
        data = {"category": self.festival.pk, "name": "Oktoberfest", "description": "d", "specificity_level": "general",
                "skill_level": "any", "fitness_required": 1, "duration_category": "varies", "cost_level": "varies",
                "best_for": "any", "indoor_outdoor": "both", "risk_level": "low", "recurrence": "yearly"}
        data.update(over)
        return data

    def test_city_must_be_in_the_country(self):
        form = ActivityEditForm(self.data(country=self.france.pk, city=self.munich.pk), instance=self.activity)
        self.assertFalse(form.is_valid())
        self.assertIn("Munich is not in France.", form.errors["city"])

    def test_saves_place_and_months(self):
        form = ActivityEditForm(self.data(city=self.munich.pk, usual_months=["10", "9"]), instance=self.activity)
        self.assertTrue(form.is_valid(), form.errors)
        activity = form.save()
        activity.refresh_from_db()
        self.assertEqual((activity.city, activity.country, activity.usual_months), (self.munich, self.germany, [9, 10]))
