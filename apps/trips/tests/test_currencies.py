"""Currency choices on a trip's forms: the trip's home currency, then the local ones, then Other…
(docs/plans/edit-by-day.md, E4)."""
import importlib
from datetime import date, timedelta
from decimal import Decimal

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import AccountSettings
from apps.approval_system.models import ApprovalStatus
from apps.locations.models import City, Country
from apps.trips.forms import LodgingForm, TransportLegForm, TripForm
from apps.trips.models import Day, Lodging, TransportLeg, Trip, TripGrant, TripRate, TripRole

User = get_user_model()


def country(name, iso, code):
    return Country.objects.create(name=name, slug=iso.lower(), iso_code=iso, iso3_code=iso + "X", continent="Europe",
                                  currency_code=code, approval_status=ApprovalStatus.APPROVED)


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        de, gb, us = country("Germany", "DE", "EUR"), country("United Kingdom", "GB", "GBP"), country("United States", "US", "USD")
        city = lambda name, c: City.objects.create(name=name, slug=name.lower(), country=c, latitude=0, longitude=0,  # noqa: E731
                                                   approval_status=ApprovalStatus.APPROVED)
        self.munich, self.london, self.pittsburgh = city("Munich", de), city("London", gb), city("Pittsburgh", us)
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 17), end_date=date(2027, 9, 22),
                                        created_by=self.editor, home_currency="USD")
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        self.trip.cities.set([self.munich, self.london])
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 17), city=self.munich)

    @staticmethod
    def codes(form, name="currency"):
        return form.fields[name].widget.get_context(name, form[name].value(), {})["widget"]["codes"]


class HomeCurrencyTests(Fixture):
    def test_a_new_trip_takes_its_creators_currency(self):
        AccountSettings.objects.update_or_create(user=self.editor, defaults={"preferred_currency": "eur"})
        self.assertEqual(Trip.objects.create(name="x", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2),
                                             created_by=self.editor).home_currency, "EUR")
        self.assertEqual(Trip.objects.create(name="y", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
                         .home_currency, "USD")  # no creator: USD
        form = TripForm(user=self.editor)
        self.assertEqual(form.initial["home_currency"], "EUR")

    def test_the_migration_fills_existing_trips_from_their_creators(self):
        AccountSettings.objects.update_or_create(user=self.editor, defaults={"preferred_currency": "GBP"})
        Trip.objects.filter(pk=self.trip.pk).update(home_currency="USD")
        migration = importlib.import_module("apps.trips.migrations.0045_home_currency")
        migration.from_creators(django_apps, None)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.home_currency, "GBP")

    def test_edit_trip_shows_it(self):
        self.client.force_login(self.editor)
        page = self.client.get(reverse("trips:trip_edit", args=[self.trip.pk]))
        self.assertContains(page, 'name="home_currency"')
        self.assertContains(page, "Home currency")


class ChoiceTests(Fixture):
    def test_germany_offers_home_and_euro_and_starts_on_euro(self):
        form = LodgingForm(instance=Lodging(trip=self.trip, city=self.munich))
        self.assertEqual(self.codes(form), ["USD", "EUR"])
        self.assertEqual(form.initial["currency"], "EUR")  # the one local currency
        london = LodgingForm(instance=Lodging(trip=self.trip, city=self.london))
        self.assertEqual(self.codes(london), ["USD", "GBP"])

    def test_a_leg_offers_both_ends_and_starts_on_home(self):
        leg = TransportLeg(trip=self.trip, origin_city=self.pittsburgh, destination_city=self.munich)
        form = TransportLegForm(instance=leg)
        self.assertEqual(self.codes(form), ["USD", "EUR"])
        self.assertEqual(form.initial["currency"], "USD")  # two local currencies: home

    def test_without_a_place_the_trips_countries(self):
        form = LodgingForm(instance=Lodging(trip=self.trip))
        self.assertEqual(self.codes(form), ["USD", "EUR", "GBP"])

    def test_an_odd_stored_code_is_shown_and_kept(self):
        stay = Lodging.objects.create(trip=self.trip, name="Inn", city=self.munich, check_in=self.day.date,
                                      check_out=self.day.date + timedelta(days=1), currency="SEK")
        form = LodgingForm(instance=stay)
        self.assertEqual(self.codes(form), ["USD", "EUR", "SEK"])
        self.assertIn('<option value="SEK" selected>', form["currency"].as_widget())


class SavingTests(Fixture):
    def post_stay(self, **currency):
        self.client.force_login(self.editor)
        data = {"name": "Hotel", "address": "", "city": self.munich.pk, "latitude": "", "longitude": "",
                "check_in": "2027-09-17", "check_out": "2027-09-18", "nightly_rate": "", "notes": "", **currency}
        return self.client.post(reverse("trips:stay_new", args=[self.trip.pk, self.day.pk]), data)

    def test_other_accepts_a_typed_code(self):
        self.post_stay(currency="__other", currency_other="chf")
        self.assertEqual(Lodging.objects.get().currency, "CHF")

    def test_a_typed_code_wins_without_picking_other(self):
        self.post_stay(currency="EUR", currency_other="NOK")  # no JavaScript: the box was simply visible
        self.assertEqual(Lodging.objects.get().currency, "NOK")

    def test_a_bad_code_is_refused(self):
        response = self.post_stay(currency="__other", currency_other="EU1")
        self.assertContains(response, "three-letter currency code")
        self.assertFalse(Lodging.objects.exists())

    def test_quick_add_legs_start_on_the_local_currency(self):
        self.client.force_login(self.editor)
        self.client.post(reverse("trips:leg_quick_add", args=[self.trip.pk, self.day.pk]),
                         {"origin": "Munich", "destination": "Munich", "mode": "train"})
        self.assertEqual(TransportLeg.objects.get().currency, "EUR")


class RatesTests(Fixture):
    def budget_queries(self):
        self.client.force_login(self.editor)
        url = reverse("trips:trip_budget", args=[self.trip.pk])
        self.client.get(url)  # warm caches
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)
        return response, len(ctx.captured_queries)

    def test_rate_selects_offer_the_trips_currencies_without_a_query_per_row(self):
        Lodging.objects.create(trip=self.trip, name="Inn", check_in=self.day.date,
                               check_out=self.day.date + timedelta(days=1), currency="GBP")
        TripRate.objects.create(trip=self.trip, from_currency="EUR", to_currency="USD", rate=Decimal("1.1"))
        response, one = self.budget_queries()
        form = response.context["rate_formset"].forms[0]
        self.assertEqual(self.codes(form, "from_currency")[:2], ["USD", "GBP"])  # home first, then those used
        for code in ("CHF", "SEK", "NOK", "DKK"):
            TripRate.objects.create(trip=self.trip, from_currency=code, to_currency="USD", rate=Decimal("1"))
        _response, five = self.budget_queries()
        self.assertEqual(five, one)
