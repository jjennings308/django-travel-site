"""The budget in one currency and the Overview's estimate (site roadmap R10)."""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.models import ExchangeRate
from apps.trips import budget
from apps.trips.models import (
    Confirmation, Day, Traveler, Trip, TripActivity, TripExpense, TripGrant, TripRate, TripRole,
)

User = get_user_model()


class CurrencyFixture(TestCase):
    def setUp(self):
        for day, usd, gbp in ((date(2027, 9, 17), "1.08", "0.84"), (date(2027, 9, 20), "1.10", "0.85")):
            ExchangeRate.objects.create(date=day, currency="USD", per_euro=Decimal(usd))
            ExchangeRate.objects.create(date=day, currency="GBP", per_euro=Decimal(gbp))
        self.ed = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 17), end_date=date(2027, 9, 22),
                                        created_by=self.ed)
        TripGrant.objects.create(trip=self.trip, user=self.ed, role=TripRole.EDITOR)
        self.james = Traveler.objects.create(name="James")
        self.regan = Traveler.objects.create(name="Regan")
        self.trip.travelers.set([self.james, self.regan])
        self.url = reverse("trips:trip_budget", args=[self.trip.pk])

    def cost(self, amount, currency, spent_on, paid_by, description="x"):
        return TripExpense.objects.create(trip=self.trip, description=description, amount=Decimal(amount),
                                          currency=currency, spent_on=spent_on, paid_by=paid_by)

    def page(self, **params):
        self.client.force_login(self.ed)
        return self.client.get(self.url, params)


class BudgetPageTests(CurrencyFixture):
    def setUp(self):
        super().setUp()
        self.cost("100", "EUR", date(2027, 9, 17), self.james, "Hotel night")   # = 108 USD that day
        self.cost("100", "EUR", date(2027, 9, 20), self.regan, "Dinner")        # = 110 USD that day
        self.cost("50", "USD", date(2027, 9, 18), self.regan, "Taxi")

    def test_each_cost_at_its_own_dates_rate(self):
        response = self.page(**{"in": "USD"})
        one = response.context["one"]
        self.assertEqual(one["total"], Decimal("268.00"))
        self.assertIn("1 EUR = 1.08 USD (ECB, Sep 17)", one["used"])
        self.assertIn("1 EUR = 1.1 USD (ECB, Sep 20)", one["used"])
        self.assertContains(response, "≈ USD 268.00")
        self.assertContains(response, "≈ USD 108.00")

    def test_settle_up_stays_per_currency_without_the_tick(self):
        summary = self.page(**{"in": "USD"}).context["summary"]
        self.assertEqual(sorted(summary), ["EUR", "USD"])

    def test_settle_in_one_currency(self):
        summary = self.page(**{"in": "USD", "settle": "1"}).context["summary"]
        self.assertEqual(list(summary), ["USD"])
        usd = summary["USD"]
        self.assertEqual(usd["total"], Decimal("268.00"))
        # James paid 108, Regan 160; each owes 134: James pays Regan 26.
        self.assertEqual([(d.name, c.name, a) for d, c, a in usd["transfers"]], [("James", "Regan", Decimal("26.00"))])

    def test_trip_rate_wins(self):
        TripRate.objects.create(trip=self.trip, from_currency="EUR", to_currency="USD", rate=Decimal("1.20"))
        one = self.page(**{"in": "USD"}).context["one"]
        self.assertEqual(one["total"], Decimal("290.00"))
        self.assertEqual(one["used"], ["1 EUR = 1.2 USD (this trip's rate)"])

    def test_unknown_currency_is_listed_not_hidden(self):
        self.cost("1000", "XYZ", date(2027, 9, 19), self.james, "Mystery")
        response = self.page(**{"in": "USD"})
        self.assertEqual([e.description for e in response.context["one"]["missing"]], ["Mystery"])
        self.assertEqual(response.context["one"]["total"], Decimal("268.00"))
        self.assertContains(response, "Not converted (no rate)")

    def test_defaults_to_the_readers_currency(self):
        self.assertEqual(self.page().context["target"], "USD")

    def test_one_currency_only_needs_no_conversion(self):
        TripExpense.objects.exclude(currency="USD").delete()
        self.assertIsNone(self.page(**{"in": "USD"}).context["one"])


class OwnRatesTests(CurrencyFixture):
    """The trip's own rates live on the Budget page (edit-by-day plan E3), saved by trips:trip_rates."""

    def rates_data(self, **row):
        data = {"rates-TOTAL_FORMS": "1", "rates-INITIAL_FORMS": "0", "rates-MIN_NUM_FORMS": "0",
                "rates-MAX_NUM_FORMS": "1000"}
        data.update({f"rates-0-{name}": value for name, value in row.items()})
        return data

    def test_editors_save_them_and_the_totals_use_them(self):
        self.cost("100", "EUR", date(2027, 9, 17), self.james)
        page = self.page()
        self.assertContains(page, 'id="rates"')
        self.assertContains(page, f'action="{reverse("trips:trip_rates", args=[self.trip.pk])}"')
        response = self.client.post(reverse("trips:trip_rates", args=[self.trip.pk]),
                                    self.rates_data(from_currency="eur", to_currency="USD", rate="1.5"))
        self.assertEqual(response["Location"], self.url + "#rates")
        rate = TripRate.objects.get()
        self.assertEqual((rate.from_currency, rate.rate), ("EUR", Decimal("1.5")))
        self.assertEqual(self.page(**{"in": "USD"}).context["one"]["total"], Decimal("150.00"))

    def test_a_mistake_shows_on_the_budget_page_and_saves_nothing(self):
        self.client.force_login(self.ed)
        response = self.client.post(reverse("trips:trip_rates", args=[self.trip.pk]),
                                    self.rates_data(from_currency="EUR", to_currency="EUR", rate="1"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pick a different currency.")
        self.assertFalse(response.context["form"].is_bound)  # the add-a-cost form isn't shown with errors
        self.assertFalse(TripRate.objects.exists())

    def test_viewers_see_them_but_cannot_change_them(self):
        TripRate.objects.create(trip=self.trip, from_currency="EUR", to_currency="USD", rate=Decimal("1.5"))
        viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        TripGrant.objects.create(trip=self.trip, user=viewer, role=TripRole.VIEWER)
        self.client.force_login(viewer)
        page = self.client.get(self.url)
        self.assertContains(page, "1 EUR = 1.5 USD")
        self.assertNotContains(page, "rates-TOTAL_FORMS")
        self.assertEqual(self.client.post(reverse("trips:trip_rates", args=[self.trip.pk]),
                                          self.rates_data(from_currency="GBP", to_currency="USD", rate="1")).status_code,
                         403)

    def test_edit_trip_no_longer_has_them(self):
        self.client.force_login(self.ed)
        self.assertNotContains(self.client.get(reverse("trips:trip_settings", args=[self.trip.pk])), 'id="rates"')


class EstimateTests(CurrencyFixture):
    def test_bookings_and_activities_in_the_readers_currency(self):
        day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 17))
        Confirmation.objects.create(trip=self.trip, confirmation_number="H1", cost=Decimal("200"), currency="EUR")
        Confirmation.objects.create(trip=self.trip, confirmation_number="F1", cost=Decimal("500"), currency="USD")
        TripActivity.objects.create(trip=self.trip, day=day, title="Tour", est_cost=Decimal("85"), currency="GBP")
        self.client.force_login(self.ed)
        response = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        estimate = response.context["cost_estimate"]
        # Latest rates: 200 EUR = 220 USD, 85 GBP = 110 USD.
        self.assertEqual((estimate["total"], estimate["currency"], estimate["approx"]), (Decimal("830.00"), "USD", True))
        self.assertEqual((estimate["bookings"], estimate["estimates"]), (2, 1))
        self.assertContains(response, "≈ USD 830.00")

    def test_nothing_with_a_cost_shows_nothing(self):
        self.client.force_login(self.ed)
        response = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        self.assertIsNone(response.context["cost_estimate"])
        self.assertNotContains(response, "Estimated trip cost")
