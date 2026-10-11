"""Trips and days name catalogue cities."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import City, Country
from apps.trips.forms import DayForm, TripForm
from apps.trips.models import Day, Trip, TripGrant, TripRole

User = get_user_model()


class TripPlacesTests(TestCase):
    def setUp(self):
        self.germany = Country.objects.create(name="Germany", slug="germany", iso_code="DE", iso3_code="DEU",
                                              continent="Europe", approval_status=ApprovalStatus.APPROVED)
        self.munich = City.objects.create(name="Munich", slug="munich", country=self.germany, latitude=48, longitude=11,
                                          approval_status=ApprovalStatus.APPROVED)
        self.berlin = City.objects.create(name="Berlin", slug="berlin", country=self.germany, latitude=52, longitude=13,
                                          approval_status=ApprovalStatus.APPROVED)
        self.trip = Trip.objects.create(name="Germany", start_date=date(2027, 9, 17), end_date=date(2027, 9, 24))
        self.ada = User.objects.create_user("ada", "ada@example.com", "pw-1234-abcd")
        TripGrant.objects.create(trip=self.trip, user=self.ada, role=TripRole.VIEWER)

    def test_trip_form_saves_cities_and_day_choices_follow(self):
        form = TripForm({"name": "Germany", "start_date": "2027-09-17", "end_date": "2027-09-24",
                         "status": "starting", "cities": [self.munich.pk]}, instance=self.trip)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(list(self.trip.cities.all()), [self.munich])
        self.assertEqual(list(DayForm(trip=self.trip).fields["city"].queryset), [self.munich])
        empty = Trip.objects.create(name="Open", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        self.assertEqual(set(DayForm(trip=empty).fields["city"].queryset), {self.munich, self.berlin})

    def test_trip_page_shows_cities_and_day_city(self):
        self.trip.cities.add(self.munich, self.berlin)
        Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 17), city=self.munich)
        self.client.force_login(self.ada)
        page = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        self.assertContains(page, reverse("locations:city_detail", args=["munich"]))
        self.assertContains(page, reverse("locations:city_detail", args=["berlin"]))

    def test_public_page_never_shows_cities(self):
        self.trip.cities.add(self.munich)
        token = self.trip.enable_public()
        self.client.logout()
        page = self.client.get(reverse("public_trip", args=[token]))
        self.assertNotContains(page, reverse("locations:city_detail", args=["munich"]))
        self.assertNotContains(page, "Munich")
