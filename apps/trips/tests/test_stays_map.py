"""Stays (Lodging) on the trip map: located from the address once, city fallback, private details never sent."""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import City, Country
from apps.trips.forms import LodgingForm
from apps.trips.models import Lodging, Trip, TripGrant, TripRole

User = get_user_model()
FOUND = (Decimal("53.408400"), Decimal("-2.991600"))


class StayFixture(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        uk = Country.objects.create(name="United Kingdom", slug="uk", iso_code="GB", iso3_code="GBR", continent="Europe",
                                    approval_status=ApprovalStatus.APPROVED)
        self.liverpool = City.objects.create(name="Liverpool", slug="liverpool", country=uk, latitude=53.41,
                                             longitude=-2.98, approval_status=ApprovalStatus.APPROVED)
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 10), end_date=date(2027, 9, 14),
                                        created_by=self.user)
        TripGrant.objects.create(trip=self.trip, user=self.user, role=TripRole.EDITOR)
        self.trip.cities.add(self.liverpool)
        self.client.force_login(self.user)

    def save(self, instance=None, **data):
        values = {"name": "Hard Days Night Hotel", "address": "Central Buildings, North John St, Liverpool",
                  "city": self.liverpool.pk, "latitude": "", "longitude": "", "check_in": "2027-09-11",
                  "check_out": "2027-09-13", "confirmation_number": "SECRET123", "nightly_rate": "189",
                  "currency": "GBP", "notes": "Room with a view"}
        if instance is not None:
            values.update({k: ("" if getattr(instance, k) is None else getattr(instance, k))
                           for k in ("latitude", "longitude")})
        values.update(data)
        form = LodgingForm(values, instance=instance or Lodging(trip=self.trip))
        self.assertTrue(form.is_valid(), form.errors)
        return form.save()


class LocateTests(StayFixture):
    @mock.patch("apps.core.geocoding.geocode", return_value=FOUND)
    def test_address_looked_up_once(self, geocode):
        stay = self.save()
        self.assertEqual((stay.latitude, stay.longitude), FOUND)
        self.save(instance=stay, notes="changed notes")
        self.assertEqual(geocode.call_count, 1)  # same address: not looked up again

    @mock.patch("apps.core.geocoding.geocode", return_value=FOUND)
    def test_changed_address_looked_up_again(self, geocode):
        stay = self.save()
        geocode.return_value = (Decimal("53.4"), Decimal("-2.9"))
        stay = self.save(instance=stay, address="Albert Dock, Liverpool")
        self.assertEqual(geocode.call_count, 2)
        self.assertEqual(stay.latitude, Decimal("53.4"))

    @mock.patch("apps.core.geocoding.geocode", return_value=FOUND)
    def test_typed_coordinates_win(self, geocode):
        stay = self.save(latitude="53.000001", longitude="-2.000001")
        geocode.assert_not_called()
        self.assertEqual(stay.latitude, Decimal("53.000001"))

    @mock.patch("time.sleep")
    @mock.patch("apps.core.geocoding.geocode", return_value=None)
    def test_failed_lookup_not_retried_until_address_changes(self, geocode, _sleep):
        stay = self.save()
        self.assertIsNone(stay.latitude)
        self.assertEqual(geocode.call_args_list[-1].args[0], "Hard Days Night Hotel, Central Buildings, North John St, Liverpool")
        self.save(instance=stay, notes="again")
        self.assertEqual(geocode.call_count, 2)  # address, then "name, address"; not again
        self.save(instance=stay, address="Somewhere else, Liverpool")
        self.assertEqual(geocode.call_count, 4)

    @mock.patch("time.sleep")
    @mock.patch("apps.core.geocoding.geocode", side_effect=[None, FOUND])
    def test_falls_back_to_name_and_address(self, geocode, _sleep):
        stay = self.save(address="Cavern Quarter")
        self.assertEqual((stay.latitude, stay.longitude), FOUND)
        self.assertEqual(geocode.call_args_list[1].args[0], "Hard Days Night Hotel, Cavern Quarter")

    @mock.patch("apps.core.geocoding.geocode")
    def test_plain_save_never_looks_up(self, geocode):
        Lodging.objects.create(trip=self.trip, name="Imported", address="1 Road", check_in=date(2027, 9, 10),
                               check_out=date(2027, 9, 11))
        geocode.assert_not_called()


class StaysLayerTests(StayFixture):
    def test_layer_has_name_dates_and_city_fallback_but_no_private_details(self):
        Lodging.objects.create(trip=self.trip, name="Pinned", address="x", latitude=FOUND[0], longitude=FOUND[1],
                               confirmation_number="SECRET123", nightly_rate=189, notes="Room with a view",
                               check_in=date(2027, 9, 11), check_out=date(2027, 9, 13))
        Lodging.objects.create(trip=self.trip, name="City only", city=self.liverpool,
                               check_in=date(2027, 9, 13), check_out=date(2027, 9, 14))
        Lodging.objects.create(trip=self.trip, name="Nowhere", check_in=date(2027, 9, 10), check_out=date(2027, 9, 11))
        response = self.client.get(reverse("trips:trip_map_data", args=[self.trip.pk]))
        stays = [f for f in response.json()["features"] if f["properties"].get("layer") == "stays"]
        self.assertEqual([s["properties"]["name"] for s in stays], ["Pinned", "City only"])
        self.assertEqual(stays[0]["geometry"]["coordinates"], [-2.9916, 53.4084])
        self.assertEqual(stays[1]["geometry"]["coordinates"], [-2.98, 53.41])
        self.assertIn("Sep 11 – Sep 13 (2 nights)", stays[0]["properties"]["subtitle"])
        self.assertIn("pin on the city centre", stays[1]["properties"]["subtitle"])
        body = response.content.decode()
        for private in ("SECRET123", "189", "Room with a view"):
            self.assertNotIn(private, body)
        page = self.client.get(reverse("trips:trip_map", args=[self.trip.pk]))
        self.assertContains(page, 'data-layer="stays"')
        self.assertContains(page, "City only")

    def test_public_view_has_no_stays(self):
        Lodging.objects.create(trip=self.trip, name="Pinned Hotel", latitude=FOUND[0], longitude=FOUND[1],
                               check_in=date(2027, 9, 11), check_out=date(2027, 9, 13))
        self.trip.enable_public()
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("public_trip", args=[self.trip.public_token])), "Pinned Hotel")

    def test_stay_city_choices_follow_the_trip(self):
        form = LodgingForm(instance=Lodging(trip=self.trip))
        self.assertEqual(list(form.fields["city"].queryset), [self.liverpool])


class FillDayCitiesTests(StayFixture):
    """A stay with a city fills the city on the nights it covers, where days have none."""

    def setUp(self):
        super().setUp()
        from apps.trips.models import Day
        uk = self.liverpool.country
        self.manchester = City.objects.create(name="Manchester", slug="manchester", country=uk, latitude=53.48,
                                              longitude=-2.24, approval_status=ApprovalStatus.APPROVED)
        self.days = {d: Day.objects.create(trip=self.trip, date=date(2027, 9, d), day_number=d - 9)
                     for d in (10, 11, 12, 13)}
        self.days[12].city = self.manchester  # set by hand: must stay
        self.days[12].save()
        self.trip.cities.clear()

    def city_of(self, day):
        self.days[day].refresh_from_db()
        return self.days[day].city

    @mock.patch("apps.core.geocoding.geocode", return_value=None)
    def test_saving_a_stay_fills_blank_nights_only(self, _geocode):
        form_stay = self.save(city=self.liverpool.pk)  # Sep 11 -> Sep 13
        self.assertEqual([self.city_of(d) for d in (10, 11, 12, 13)], [None, self.liverpool, self.manchester, None])
        self.assertIn(self.liverpool, self.trip.cities.all())
        self.assertIsNotNone(form_stay.pk)

    @mock.patch("apps.core.geocoding.geocode", return_value=None)
    def test_stay_without_city_changes_nothing(self, _geocode):
        self.save(city="")
        self.assertIsNone(self.city_of(11))

    def test_plain_create_does_not_fill(self):
        Lodging.objects.create(trip=self.trip, name="Imported", city=self.liverpool,
                               check_in=date(2027, 9, 11), check_out=date(2027, 9, 13))
        self.assertIsNone(self.city_of(11))

    def test_backfill_command(self):
        from io import StringIO
        from django.core.management import call_command
        Lodging.objects.create(trip=self.trip, name="Imported", city=self.liverpool,
                               check_in=date(2027, 9, 10), check_out=date(2027, 9, 12))
        out = StringIO()
        call_command("geocode_stays", "--fill-days", stdout=out)
        self.assertEqual([self.city_of(d) for d in (10, 11)], [self.liverpool, self.liverpool])
        self.assertIn("2 day city(ies) filled", out.getvalue())

    @mock.patch("apps.core.geocoding.geocode", return_value=None)
    def test_trip_edit_page_says_how_many(self, _geocode):
        Lodging.objects.create(trip=self.trip, name="Hard Days Night Hotel", city=self.liverpool,
                               check_in=date(2027, 9, 11), check_out=date(2027, 9, 13))
        page = self.client.get(reverse("trips:trip_edit", args=[self.trip.pk]))
        data = {}
        for key, value in self._form_data(page).items():
            data[key] = value
        stay_prefix = "lodging-0-"
        data[stay_prefix + "notes"] = "edited"
        response = self.client.post(reverse("trips:trip_edit", args=[self.trip.pk]), data, follow=True)
        self.assertContains(response, "Filled in the city for 1 day from your stays; change any day trips by hand.")

    @staticmethod
    def _form_data(page):
        """Every field the edit page would submit, from its bound forms' initial values."""
        context = page.context
        data = {}
        form = context["form"]
        for name, field in form.fields.items():
            value = form[name].value()
            if value is None:
                continue
            data[form.add_prefix(name)] = [str(v) for v in value] if isinstance(value, (list, tuple)) else str(value)
        traveler_form = context["traveler_form"]
        for name in traveler_form.fields:
            data[traveler_form.add_prefix(name)] = ""
        for _key, _label, formset in context["formsets"]:
            mf = formset.management_form
            for name in mf.fields:
                data[mf.add_prefix(name)] = str(mf[name].value())
            for f in formset.forms:
                for name in f.fields:
                    value = f[name].value()
                    if value is None or value is False:
                        continue
                    if isinstance(value, (list, tuple)):
                        data[f.add_prefix(name)] = [str(v) for v in value]
                    else:
                        data[f.add_prefix(name)] = str(value)
        return data
