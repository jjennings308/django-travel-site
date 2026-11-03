"""Costs with no currency take their place's (docs/plans/blank-currencies.md, CU1): ``currencies.currency_of`` —
stored, else the trip activity's place's entry-fee currency, the place's city, the day's city, else the trip's
``default_for`` — used by the day's notes, the Budget page, choices and the edit forms; ``fill_currencies`` stores
it; a place's entry fee is offered as an activity's estimate."""
from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.core.models import ExchangeRate
from apps.locations.models import POI, City
from apps.trips import currencies
from apps.trips.models import (Confirmation, Day, Lodging, Meal, Option, OptionGroup, TransportLeg, Traveler, Trip,
                               TripActivity, TripChange, TripGrant, TripRole)
from apps.trips.tests.test_currencies import country

User = get_user_model()
D = Decimal


class Fixture(TestCase):
    """A USD trip through Munich (Day 1), Schwangau (Day 2) and London (Day 3); Day 4 has no city."""

    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        de, gb = country("Germany", "DE", "EUR"), country("United Kingdom", "GB", "GBP")
        city = lambda name, c: City.objects.create(name=name, slug=name.lower(), country=c, latitude=0, longitude=0,  # noqa: E731
                                                   approval_status=ApprovalStatus.APPROVED)
        self.munich, self.schwangau, self.london = city("Munich", de), city("Schwangau", de), city("London", gb)
        place = lambda name, c, **fee: POI.objects.create(  # noqa: E731
            name=name, slug=name.lower().replace(" ", "-"), city=c, latitude=0, longitude=0,
            approval_status=ApprovalStatus.APPROVED, **fee)
        self.neuschwanstein = place("Neuschwanstein Castle", self.schwangau)
        self.hohenschwangau = place("Hohenschwangau Castle", self.schwangau, entry_fee=D("21"),
                                    entry_fee_currency="EUR")
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 17), end_date=date(2027, 9, 20),
                                        created_by=self.editor, home_currency="USD")
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        self.trip.travelers.set([Traveler.objects.create(name="Ada"), Traveler.objects.create(name="Bo")])
        cities = [self.munich, self.schwangau, self.london, None]
        self.days = [Day.objects.create(trip=self.trip, day_number=n, date=date(2027, 9, 16 + n), city=cities[n - 1])
                     for n in (1, 2, 3, 4)]
        self.client.force_login(self.editor)

    def activity(self, n=2, **fields):
        fields.setdefault("title", "Castle tour")
        return TripActivity.objects.create(trip=self.trip, day=self.days[n - 1], **fields)

    def fresh(self):
        return Trip.objects.get(pk=self.trip.pk)


class CurrencyOfTests(Fixture):
    def test_the_stored_code_wins(self):
        self.assertEqual(currencies.currency_of(self.activity(currency="chf"), self.trip), "CHF")

    def test_an_activity_falls_back_through_fee_place_day_and_home(self):
        london_sight = POI.objects.create(name="Tower", slug="tower", city=self.london, latitude=0, longitude=0,
                                          approval_status=ApprovalStatus.APPROVED, entry_fee=D("30"),
                                          entry_fee_currency="EUR")
        trip = self.fresh()
        cases = [
            (self.activity(n=3, poi=london_sight), "EUR"),  # the place's own fee currency, before its city's
            (self.activity(n=3, poi=self.neuschwanstein), "EUR"),  # the place's city, before the day's
            (self.activity(n=3), "GBP"),  # no place: the day's city
            (self.activity(n=4), "USD"),  # no city: two countries on the trip → home
        ]
        for item, code in cases:
            self.assertEqual(currencies.currency_of(item, trip), code, item)

    def test_each_kind(self):
        trip = self.fresh()
        leg = TransportLeg.objects.create(trip=self.trip, mode="train", origin="London", destination="Munich",
                                          date=self.days[0].date, origin_city=self.london, currency="")
        stay = Lodging.objects.create(trip=self.trip, name="Inn", check_in=self.days[2].date,
                                      check_out=self.days[3].date, city=self.munich, currency="")
        meal = Meal.objects.create(day=self.days[2], name="Lunch", poi=self.neuschwanstein)
        plain_meal = Meal.objects.create(day=self.days[2], name="Tea")
        group = OptionGroup.objects.create(trip=self.trip, day=self.days[1], prompt="Lunch?")
        here, there = (Option.objects.create(group=group, title="Here"),
                       Option.objects.create(group=group, title="There", city=self.london))
        for item, code in ((leg, "GBP"), (stay, "EUR"), (meal, "EUR"), (plain_meal, "GBP"), (here, "EUR"),
                           (there, "GBP")):
            self.assertEqual(currencies.currency_of(item, trip), code, item)

    def test_a_confirmation_takes_the_places_it_covers_when_they_agree(self):
        castle = self.activity(poi=self.neuschwanstein)
        lunch = Meal.objects.create(day=self.days[0], name="Lunch")
        tea = Meal.objects.create(day=self.days[2], name="Tea")
        both = Confirmation.objects.create(trip=self.trip, confirmation_number="DE1", cost=D("50"))
        both.link(castle)
        both.link(lunch)
        mixed = Confirmation.objects.create(trip=self.trip, confirmation_number="MIX", cost=D("50"))
        mixed.link(castle)
        mixed.link(tea)
        self.assertEqual(currencies.currency_of(both, self.fresh()), "EUR")
        self.assertEqual(currencies.currency_of(mixed, self.fresh()), "USD")  # EUR and GBP: home


class ShownTests(Fixture):
    def test_the_day_shows_the_places_currency(self):
        self.activity(poi=self.neuschwanstein, est_cost=D("104"))  # total, for two: €52 each
        page = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        self.assertIn("≈ €52 pp", page)
        self.assertNotIn("≈ 52 pp", page)

    def test_the_budget_counts_it_in_euros_converted(self):
        ExchangeRate.objects.create(date=date(2027, 9, 1), currency="USD", per_euro=D("1.10"))
        self.activity(poi=self.neuschwanstein, est_cost=D("100"))
        plan = self.client.get(reverse("trips:trip_budget", args=[self.trip.pk]) + "?in=USD").context["plan"]
        activities = next(c for c in plan["categories"] if c["key"] == "activities")
        self.assertEqual(activities["planned"], D("110.00"))  # €100, not $100
        self.assertIn("€100", activities["rows"][0]["line"])

    def test_a_choice_box_line_names_it(self):
        group = OptionGroup.objects.create(trip=self.trip, day=self.days[1], prompt="Lunch?", kind="eat")
        option = Option.objects.create(group=group, title="Bräustüberl", est_cost=D("40"))
        self.assertEqual(option.kind_line(), "EUR 40.00")

    def test_the_edit_form_starts_on_it(self):
        castle = self.activity(poi=self.neuschwanstein, est_cost=D("52"))
        url = reverse("trips:activity_edit", args=[self.trip.pk, self.days[1].pk, castle.pk])
        self.assertEqual(self.client.get(url).context["form"]["currency"].value(), "EUR")
        kept = self.activity(poi=self.neuschwanstein, est_cost=D("52"), currency="CHF")
        url = reverse("trips:activity_edit", args=[self.trip.pk, self.days[1].pk, kept.pk])
        self.assertEqual(self.client.get(url).context["form"]["currency"].value(), "CHF")


class FillTests(Fixture):
    def run_command(self, *args):
        out = StringIO()
        call_command("fill_currencies", "--trip", str(self.trip.pk), *args, stdout=out)
        return out.getvalue()

    def test_dry_run_lists_and_apply_saves_with_one_history_line(self):
        castle = self.activity(title="Neuschwanstein Castle", poi=self.neuschwanstein, est_cost=D("52"))
        fee = self.activity(title="Hohenschwangau", poi=self.hohenschwangau, est_cost=D("21"))
        leg = TransportLeg.objects.create(trip=self.trip, mode="train", origin="London", destination="Munich",
                                          date=self.days[2].date, origin_city=self.london, cost=D("90"), currency="")
        unpriced = self.activity(title="Walk")
        before = TripChange.objects.filter(trip=self.trip).count()  # creating them was recorded
        out = self.run_command()
        self.assertIn("Neuschwanstein Castle (Day 2): EUR, from Schwangau", out)
        self.assertIn("Hohenschwangau (Day 2): EUR, Hohenschwangau Castle's entry fee", out)
        self.assertIn("London → Munich (Day 3): GBP, from London", out)
        self.assertNotIn("Walk", out)
        self.assertIn("Dry run: 3", out)
        castle.refresh_from_db()
        self.assertEqual(castle.currency, "")
        self.assertEqual(TripChange.objects.filter(trip=self.trip).count(), before)

        self.run_command("--apply")
        for item, code in ((castle, "EUR"), (fee, "EUR"), (leg, "GBP"), (unpriced, "")):
            item.refresh_from_db()
            self.assertEqual(item.currency, code, item)
        lines = list(TripChange.objects.filter(trip=self.trip).order_by("pk").values_list("summary", flat=True))
        self.assertEqual(lines[before:], ["Filled in 3 missing currencies"])
        self.assertIn("No costs without a currency.", self.run_command("--apply"))


class FeeOfferTests(Fixture):
    def test_an_activity_with_no_estimate_is_offered_its_places_fee(self):
        tour = self.activity(poi=self.hohenschwangau)
        url = reverse("trips:activity_edit", args=[self.trip.pk, self.days[1].pk, tour.pk])
        page = self.client.get(url).content.decode()
        self.assertIn("Use Hohenschwangau Castle&#x27;s entry fee: €21 per person", page)
        tour.refresh_from_db()
        self.assertIsNone(tour.est_cost)  # never filled in silently
        response = self.client.post(reverse("trips:activity_use_fee", args=[self.trip.pk, self.days[1].pk, tour.pk]),
                                    {"next": url})
        self.assertRedirects(response, url)
        tour.refresh_from_db()
        self.assertEqual((tour.est_cost, tour.currency, tour.cost_basis), (D("21.00"), "EUR", "person"))
        self.assertNotIn("data-fee-offer", self.client.get(url).content.decode())

    def test_no_offer_with_an_estimate_or_no_fee(self):
        for tour in (self.activity(poi=self.hohenschwangau, est_cost=D("30")), self.activity(poi=self.neuschwanstein)):
            url = reverse("trips:activity_edit", args=[self.trip.pk, self.days[1].pk, tour.pk])
            self.assertNotIn("data-fee-offer", self.client.get(url).content.decode())


class ActivityPageTests(Fixture):
    def test_the_page_shows_currency_and_basis_and_saving_keeps_them(self):
        self.trip.cities.set([self.munich, self.schwangau, self.london])
        castle = self.activity(poi=self.neuschwanstein, est_cost=D("52"), cost_basis="person")
        url = reverse("trips:activity_edit", args=[self.trip.pk, self.days[1].pk, castle.pk])
        page = self.client.get(url).content.decode()
        self.assertIn("data-cost-fields", page)
        self.assertIn('name="currency"', page)
        self.assertIn('name="cost_basis"', page)
        form = self.client.get(url).context["form"]
        data = {name: form[name].value() for name in form.fields if form[name].value() is not None}
        data["travelers"] = []
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
        castle.refresh_from_db()
        self.assertEqual((castle.currency, castle.cost_basis, castle.est_cost), ("EUR", "person", D("52.00")))
