"""Filled in from the catalogue (docs/plans/edit-by-day.md, E5): a leg's zones from its cities, and
city selects that list the trip's own cities first and let any other one join the trip."""
from datetime import date, datetime, timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import City, Country
from apps.trips.forms import DayForm, LodgingForm, TransportLegForm
from apps.trips.models import Day, Lodging, TransportLeg, Trip, TripGrant, TripRole

User = get_user_model()


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        us = Country.objects.create(name="United States", slug="us", iso_code="US", iso3_code="USA",
                                    continent="North America", approval_status=ApprovalStatus.APPROVED)
        de = Country.objects.create(name="Germany", slug="de", iso_code="DE", iso3_code="DEU", continent="Europe",
                                    approval_status=ApprovalStatus.APPROVED)

        def city(name, country, zone):
            return City.objects.create(name=name, slug=name.lower(), country=country, latitude=0, longitude=0,
                                       timezone=zone, approval_status=ApprovalStatus.APPROVED)

        self.pittsburgh = city("Pittsburgh", us, "America/New_York")
        self.frankfurt = city("Frankfurt", de, "Europe/Berlin")
        self.munich = city("Munich", de, "Europe/Berlin")
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 17), end_date=date(2027, 9, 22),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        self.trip.cities.set([self.frankfurt])
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 17))

    def leg_form(self, **over):
        data = {"mode": "plane", "date": "", "origin": "", "origin_city": self.pittsburgh.pk, "origin_timezone": "",
                "departure_local": "2027-09-17T18:00", "destination": "", "destination_city": self.frankfurt.pk,
                "destination_timezone": "", "arrival_local": "2027-09-18T08:00", "currency": "USD"}
        data.update(over)
        return TransportLegForm(data, instance=TransportLeg(trip=self.trip))


class LegZoneTests(Fixture):
    def test_blank_zones_and_names_come_from_the_cities(self):
        form = self.leg_form()
        self.assertTrue(form.is_valid(), form.errors)
        leg = form.save()
        self.assertEqual((leg.origin_timezone, leg.destination_timezone), ("America/New_York", "Europe/Berlin"))
        self.assertEqual((leg.origin, leg.destination), ("Pittsburgh", "Frankfurt"))
        self.assertEqual(leg.departure_at, datetime(2027, 9, 17, 22, 0, tzinfo=timezone.utc))  # 6 PM EDT
        self.assertEqual(leg.arrival_at, datetime(2027, 9, 18, 6, 0, tzinfo=timezone.utc))  # 8 AM CEST

    def test_a_zone_or_name_typed_in_is_kept(self):
        form = self.leg_form(origin="PIT", origin_timezone="America/Chicago")
        self.assertTrue(form.is_valid(), form.errors)
        leg = form.save()
        self.assertEqual((leg.origin, leg.origin_timezone), ("PIT", "America/Chicago"))

    def test_quick_add_fills_zones_from_the_matched_cities(self):
        self.client.force_login(self.editor)
        self.client.post(reverse("trips:leg_quick_add", args=[self.trip.pk, self.day.pk]),
                         {"origin": "Frankfurt", "destination": "Munich", "mode": "train"})
        leg = TransportLeg.objects.get()
        self.assertEqual((leg.origin_timezone, leg.destination_timezone), ("Europe/Berlin", "Europe/Berlin"))

    def test_the_leg_page_tags_cities_with_their_zones(self):
        leg = TransportLeg.objects.create(trip=self.trip, mode="train", origin="A", destination="B", date=self.day.date)
        self.client.force_login(self.editor)
        html = self.client.get(reverse("trips:leg_edit", args=[self.trip.pk, leg.pk])).content.decode()
        self.assertIn(f'value="{self.frankfurt.pk}" data-tz="Europe/Berlin"', html)
        self.assertIn('select[name="\' + pair[0] + \'"]', html)  # the fill script
        self.assertIn("Filled in from the city", html)


class CitySelectTests(Fixture):
    def groups(self, form, name):
        return {label: [pk for pk, _ in items] for label, items in form.fields[name].choices[1:]}

    def test_the_trips_cities_come_first_on_new_and_existing_rows(self):
        existing = TransportLeg.objects.create(trip=self.trip, mode="train", origin="A", destination="B",
                                               origin_city=self.munich, date=self.day.date)
        for form in (TransportLegForm(instance=TransportLeg(trip=self.trip)), TransportLegForm(instance=existing),
                     LodgingForm(instance=Lodging(trip=self.trip)), DayForm(instance=self.day, trip=self.trip)):
            name = "city" if "city" in form.fields else "origin_city"
            with self.subTest(form=type(form).__name__):
                groups = self.groups(form, name)
                self.assertEqual(groups["This trip"], [self.frankfurt.pk])
                self.assertEqual(set(groups["Everywhere else"]), {self.munich.pk, self.pittsburgh.pk})

    def test_a_city_from_everywhere_else_joins_the_trip(self):
        self.client.force_login(self.editor)
        self.client.post(reverse("trips:stay_new", args=[self.trip.pk, self.day.pk]), {
            "name": "Hotel", "address": "", "city": self.munich.pk, "latitude": "", "longitude": "",
            "check_in": "2027-09-17", "check_out": "2027-09-18", "nightly_rate": "", "currency": "EUR", "notes": ""})
        self.assertIn(self.munich, self.trip.cities.all())
        form = self.leg_form()
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertIn(self.pittsburgh, self.trip.cities.all())
