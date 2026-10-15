"""'Also add the return trip' on a transport leg: a second leg back the other way."""
from datetime import date, datetime, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import City, Country
from apps.trips.forms import TransportLegForm
from apps.trips.models import TransportLeg, Trip, TripGrant, TripRole

User = get_user_model()
UTC = dt_timezone.utc


class RoundTripTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        de = Country.objects.create(name="Germany", slug="de", iso_code="DE", iso3_code="DEU", continent="Europe",
                                    approval_status=ApprovalStatus.APPROVED)
        uk = Country.objects.create(name="United Kingdom", slug="uk", iso_code="GB", iso3_code="GBR",
                                    continent="Europe", approval_status=ApprovalStatus.APPROVED)
        self.munich = City.objects.create(name="Munich", slug="munich", country=de, latitude=48.14, longitude=11.58,
                                          approval_status=ApprovalStatus.APPROVED)
        self.london = City.objects.create(name="London", slug="london", country=uk, latitude=51.5, longitude=-0.12,
                                          approval_status=ApprovalStatus.APPROVED)
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 7, 1), end_date=date(2027, 7, 10),
                                        created_by=self.user)
        TripGrant.objects.create(trip=self.trip, user=self.user, role=TripRole.EDITOR)
        self.trip.cities.set([self.munich, self.london])

    def data(self, **over):
        values = {
            "mode": "plane", "origin": "MUC", "origin_city": self.munich.pk, "origin_timezone": "Europe/Berlin",
            "departure_local": "2027-07-02 09:00", "destination": "LHR", "destination_city": self.london.pk,
            "destination_timezone": "Europe/London", "arrival_local": "2027-07-02 10:00", "operator": "Lufthansa",
            "service_number": "LH2470", "cost": "199", "currency": "EUR",
            "notes": "Window seat", "add_return": "on",
            "return_departure_local": "2027-07-05 18:00", "return_arrival_local": "2027-07-05 21:00",
        }
        values.update(over)
        return values

    def form(self, **over):
        return TransportLegForm(self.data(**over), instance=TransportLeg(trip=self.trip))

    def test_return_leg_swaps_the_ends_and_converts_in_the_swapped_zones(self):
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        outbound = form.save()
        back = form.return_leg
        self.assertEqual(TransportLeg.objects.count(), 2)
        self.assertEqual((back.origin, back.destination, back.origin_city, back.destination_city),
                         ("LHR", "MUC", self.london, self.munich))
        self.assertEqual((back.origin_timezone, back.destination_timezone), ("Europe/London", "Europe/Berlin"))
        self.assertEqual((back.mode, back.operator, back.currency), ("plane", "Lufthansa", "EUR"))
        self.assertEqual((back.service_number, back.cost, back.notes), ("", None, ""))
        self.assertFalse(back.confirmations.exists())  # a booking reference isn't copied to the return
        # 18:00 in London (BST, UTC+1) = 17:00 UTC; 21:00 in Munich (CEST, UTC+2) = 19:00 UTC
        self.assertEqual(back.departure_at, datetime(2027, 7, 5, 17, 0, tzinfo=UTC))
        self.assertEqual(back.arrival_at, datetime(2027, 7, 5, 19, 0, tzinfo=UTC))
        self.assertEqual(outbound.service_number, "LH2470")

    def test_unticked_makes_one_leg(self):
        form = self.form(add_return="", return_departure_local="", return_arrival_local="")
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(TransportLeg.objects.count(), 1)
        self.assertIsNone(form.return_leg)

    def test_return_needs_times_or_a_day_when_ticked(self):
        form = self.form(return_departure_local="", return_arrival_local="")
        self.assertFalse(form.is_valid())
        self.assertIn("return_date", form.errors)
        form = self.form(return_arrival_local="")  # one time without the other
        self.assertFalse(form.is_valid())
        self.assertIn("return_arrival_local", form.errors)

    def test_return_cannot_arrive_before_it_departs(self):
        form = self.form(return_arrival_local="2027-07-05 16:00")  # 14:00 UTC, before 17:00 UTC
        self.assertFalse(form.is_valid())
        self.assertIn("return_arrival_local", form.errors)

    def test_return_cannot_leave_before_the_outbound_arrives(self):
        form = self.form(return_departure_local="2027-07-02 08:00", return_arrival_local="2027-07-02 11:00")
        self.assertFalse(form.is_valid())
        self.assertIn("return_departure_local", form.errors)

    def test_ticked_on_an_existing_leg_adds_one_return(self):
        form = self.form(add_return="", return_departure_local="", return_arrival_local="")
        self.assertTrue(form.is_valid(), form.errors)
        leg = form.save()
        form = TransportLegForm(self.data(), instance=leg)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(TransportLeg.objects.count(), 2)

    def test_trip_map_draws_both(self):
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.client.force_login(self.user)
        data = self.client.get(reverse("trips:trip_map_data", args=[self.trip.pk])).json()
        names = [f["properties"]["name"] for f in data["features"] if f["geometry"]["type"] == "LineString"]
        self.assertEqual(names, ["Flight: Munich → London", "Flight: London → Munich"])
