"""The planned budget (docs/plans/budget-estimates.md, B2): the Budget page's Plan — rows by category, booked over
estimated, undecided ranges, the daily food allowance, totals, each traveller's share, one currency."""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.core.models import ExchangeRate
from apps.trips.models import (Confirmation, Day, Lodging, Meal, Option, OptionGroup, TransportLeg, Traveler, Trip,
                               TripActivity, TripExpense, TripGrant, TripRole)

User = get_user_model()
D = Decimal


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        from apps.accounts.models import AccountSettings
        AccountSettings.objects.update_or_create(user=self.editor, defaults={"preferred_currency": "EUR"})
        self.trip = Trip.objects.create(name="Bavaria", start_date=date(2027, 9, 20), end_date=date(2027, 9, 23),
                                        created_by=self.editor, home_currency="EUR")
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        self.ada, self.bo = Traveler.objects.create(name="Ada"), Traveler.objects.create(name="Bo")
        self.trip.travelers.set([self.ada, self.bo])
        self.days = [Day.objects.create(trip=self.trip, day_number=n, date=date(2027, 9, 19 + n)) for n in (1, 2, 3)]

    def leg(self, origin="Augsburg", destination="Munich", n=0, **fields):
        fields.setdefault("currency", "EUR")
        return TransportLeg.objects.create(trip=self.trip, mode="train", operator="DB", origin=origin,
                                           destination=destination, date=self.days[n].date, **fields)

    def plan(self, query=""):
        self.client.force_login(self.editor)
        response = self.client.get(reverse("trips:trip_budget", args=[self.trip.pk]) + query)
        self.assertEqual(response.status_code, 200)
        return response.context["plan"], response.content.decode()

    def category(self, plan, key):
        return next(c for c in plan["categories"] if c["key"] == key)


class RowTests(Fixture):
    def test_a_booking_over_several_legs_is_one_row_and_their_estimates_step_aside(self):
        legs = [self.leg(n=i, cost=D("40")) for i in range(3)]
        booking = Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS", cost=D("100"),
                                              currency="EUR")
        for leg in legs:
            booking.link(leg)
        self.leg(origin="Munich", destination="Füssen", cost=D("25"))  # estimated
        plan, html = self.plan()
        travel = self.category(plan, "travel")
        self.assertEqual([(r["label"], r["status"]) for r in travel["rows"]],
                         [("GCH7JS · 3 journeys", "booked"), ("Munich → Füssen", "estimated")])
        self.assertEqual((travel["planned"], travel["booked"]), (D("125.00"), D("100.00")))
        self.assertIn("GCH7JS · 3 journeys", html)

    def test_stays_activities_meals_and_items_with_no_plan(self):
        Lodging.objects.create(trip=self.trip, name="Hotel Augusta", check_in=self.days[0].date,
                               check_out=self.days[2].date, nightly_rate=D("95"), currency="EUR",
                               cost_basis="room_night", rooms=1)
        TripActivity.objects.create(trip=self.trip, day=self.days[1], title="Castle", est_cost=D("8"), currency="EUR",
                                    cost_basis="person")
        Meal.objects.create(day=self.days[1], name="Augustiner", est_cost=D("30"), currency="EUR")
        Meal.objects.create(day=self.days[1], name="Snack")  # no estimate: not a budget line
        self.leg()  # no cost: "no plan"
        self.leg(origin="Munich", destination="Ulm", no_booking=True)
        plan, _ = self.plan()
        self.assertEqual(self.category(plan, "stays")["planned"], D("190.00"))
        self.assertEqual(self.category(plan, "activities")["planned"], D("16.00"))
        food = self.category(plan, "food")
        self.assertEqual([r["label"] for r in food["rows"]], ["Augustiner"])
        self.assertEqual(food["planned"], D("60.00"))
        statuses = {r["label"]: r["status"] for r in self.category(plan, "travel")["rows"]}
        self.assertEqual(statuses, {"Augsburg → Munich": "no plan", "Munich → Ulm": "no booking needed"})

    def test_a_loose_booking_is_other(self):
        Confirmation.objects.create(trip=self.trip, confirmation_number="INS-1", label="Travel insurance",
                                    cost=D("120"), currency="EUR")
        plan, _ = self.plan()
        self.assertEqual([r["label"] for r in self.category(plan, "other")["rows"]], ["Travel insurance"])

    def test_undecided_choices_are_a_range_outside_the_totals_chosen_ones_count(self):
        group = OptionGroup.objects.create(trip=self.trip, day=self.days[0], prompt="Where to stay", kind="stay",
                                           nights=2)
        Option.objects.create(group=group, title="Hotel", est_cost=D("95"), currency="EUR")
        Option.objects.create(group=group, title="Flat", est_cost=D("80"), currency="EUR")
        plan, html = self.plan()
        stays = self.category(plan, "stays")
        self.assertEqual(stays["rows"][0]["range"], (D("160.00"), D("190.00")))
        self.assertEqual(stays["planned"], D("0"))
        self.assertIn("Undecided, not counted", html)
        group.pick(group.options.get(title="Flat"))
        plan, _ = self.plan()
        stays = self.category(plan, "stays")
        self.assertEqual(([r["label"] for r in stays["rows"]], stays["planned"]), (["Where to stay: Flat"], D("160.00")))


class AllowanceTests(Fixture):
    def test_per_person_per_day_skipping_meals_included(self):
        self.trip.food_allowance, self.trip.food_allowance_currency = D("45"), "EUR"
        self.trip.save()
        self.days[2].meals_included = True
        self.days[2].save()
        plan, _ = self.plan()
        row = self.category(plan, "food")["rows"][0]
        self.assertEqual(row["line"], "€45 per person per day × 2 days × 2 = €180 · 1 day with meals included skipped")
        self.assertEqual(row["planned"], D("180"))

    def test_settings_saves_it(self):
        self.client.force_login(self.editor)
        data = {"name": "Bavaria", "start_date": "2027-09-20", "end_date": "2027-09-23", "status": "starting",
                "home_currency": "EUR", "home_currency_other": "", "food_allowance": "45",
                "food_allowance_currency": "EUR", "food_allowance_currency_other": "", "destination": "", "notes": "",
                "new_traveler_name": "", "travelers": [self.ada.pk, self.bo.pk]}
        self.client.post(reverse("trips:trip_settings", args=[self.trip.pk]), data)
        self.trip.refresh_from_db()
        self.assertEqual((self.trip.food_allowance, self.trip.food_allowance_currency), (D("45"), "EUR"))


class TotalsTests(Fixture):
    def test_paid_and_left_by_category_and_each_persons_share(self):
        self.leg(cost=D("100"))
        TripExpense.objects.create(trip=self.trip, category="flights", description="Train", amount=D("30"),
                                   currency="EUR", paid_by=self.ada, spent_on=self.days[0].date)
        TripExpense.objects.create(trip=self.trip, category="food", description="Lunch", amount=D("20"),
                                   currency="EUR", paid_by=self.bo, spent_on=self.days[0].date)
        plan, html = self.plan()
        travel = self.category(plan, "travel")
        self.assertEqual((travel["planned"], travel["paid"], travel["left"]), (D("100.00"), D("30.00"), D("70.00")))
        food = self.category(plan, "food")
        self.assertEqual((food["planned"], food["paid"], food["left"]), (D("0"), D("20.00"), D("0")))  # never below 0
        self.assertEqual(plan["totals"]["left"], D("70.00"))
        people = {p["person"].name: (p["share"], p["paid"]) for p in plan["people"]}
        self.assertEqual(people, {"Ada": (D("50.00"), D("30.00")), "Bo": (D("50.00"), D("20.00"))})
        self.assertIn("data-plan-people", html)

    def test_a_number_of_people_isnt_split_by_name(self):
        self.leg(cost=D("90"), cost_people=3)
        plan, _ = self.plan()
        self.assertEqual(plan["unassigned"], D("90.00"))

    def test_converted_into_the_page_currency_and_a_missing_rate_listed(self):
        ExchangeRate.objects.create(date=date(2027, 9, 1), currency="USD", per_euro=D("1.10"))
        self.leg(cost=D("100"))
        self.leg(origin="Munich", destination="Bern", cost=D("50"), currency="CHF")
        plan, html = self.plan("?in=USD")
        travel = self.category(plan, "travel")
        self.assertEqual(travel["planned"], D("110.00"))
        self.assertTrue(plan["approx"])
        self.assertEqual(len(plan["missing"]), 1)
        self.assertIn("Not converted (no rate)", html)


class PageTests(Fixture):
    def test_rows_link_to_the_item_on_the_trip_page(self):
        leg = self.leg(cost=D("100"))
        _, html = self.plan()
        self.assertIn(f'href="{reverse("trips:trip_detail", args=[self.trip.pk])}?item=leg-{leg.pk}#leg-{leg.pk}"', html)
        self.assertIn('data-plan-line>ⓘ', html)

    def test_a_fixed_number_of_queries_however_many_items(self):
        def one_of_each(n, tag):
            self.leg(origin=f"A{tag}", destination=f"B{tag}", n=n, cost=D("10"))
            Meal.objects.create(day=self.days[n], name=f"Meal {tag}", est_cost=D("12"), currency="EUR")
            TripActivity.objects.create(trip=self.trip, day=self.days[n], title=f"Tour {tag}", est_cost=D("9"),
                                        currency="EUR")
            Lodging.objects.create(trip=self.trip, name=f"Inn {tag}", check_in=self.days[n].date,
                                   check_out=self.days[n].date, nightly_rate=D("50"), currency="EUR")
        one_of_each(0, "first")  # each kind's prefetch runs once there is one (Django skips an empty one)
        self.client.force_login(self.editor)
        url = reverse("trips:trip_budget", args=[self.trip.pk])

        def count():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(url)
            return len(ctx.captured_queries)
        count()
        before = count()
        for n in range(3):
            one_of_each(n, n)
        self.assertEqual(count(), before)

    def test_the_trip_page_says_planned_and_booked(self):
        self.leg(cost=D("100"))
        booking = Confirmation.objects.create(trip=self.trip, confirmation_number="X1", cost=D("40"), currency="EUR")
        booking.link(self.leg(origin="Munich", destination="Ulm"))
        self.client.force_login(self.editor)
        html = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        self.assertIn("EUR 140.00 planned</strong> · EUR 40.00 booked", html)
