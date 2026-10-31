"""The booklet's budget version (docs/plans/booklet-budget.md, BB1): ``trip_pdf?budget=1`` adds one page of totals and
a "to pay" line under the items; the plain booklet is unchanged (its own snapshot). The budget version is pinned too:

    UPDATE_SNAPSHOTS=1 python manage.py test apps.trips.tests.test_booklet_budget

rewrites ``snapshots/booklet_budget.html``; review the diff before committing it."""
import difflib
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.trips import budget_plan
from apps.trips.models import (Confirmation, Day, Lodging, Meal, TransportLeg, Traveler, Trip, TripActivity,
                               TripExpense, TripGrant, TripRole)
from apps.trips.tests.test_booklet_snapshot import build_trip, normalise

User = get_user_model()
D = Decimal
SNAPSHOT = Path(__file__).parent / "snapshots" / "booklet_budget.html"


def warm_content_types():
    for model in ("transportleg", "lodging", "tripactivity", "meal", "confirmation"):
        ContentType.objects.get_by_natural_key("trips", model)


class Fixture(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.client.force_login(self.user)

    def grant(self, trip, role=TripRole.EDITOR):
        TripGrant.objects.create(trip=trip, user=self.user, role=role)

    def booklet(self, trip, budget=True):
        captured = {}

        def fake(html, base_url):
            captured["html"] = html
            return b"%PDF"
        url = reverse("trips:trip_pdf", args=[trip.pk]) + ("?budget=1" if budget else "")
        with mock.patch("apps.trips.pdf.render_pdf", side_effect=fake), \
                mock.patch("apps.trips.views.django_timezone.localdate", return_value=date(2027, 8, 15)):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response, captured["html"]


class SnapshotTests(Fixture):
    def build(self):
        trip = build_trip()
        trip.home_currency = "EUR"
        trip.save()
        ada, bo = trip.travelers.order_by("name")
        # A costed booking with a part payment: GCH7JS (the overnight flight) €900, €400 paid against the booking.
        pnr = trip.confirmations.get(confirmation_number="GCH7JS")
        pnr.cost, pnr.currency = D("900"), "EUR"
        pnr.save()
        paid = TripExpense(trip=trip, description="Flight deposit", amount=D("400"), currency="EUR", paid_by=ada,
                           category="flights", spent_on=date(2027, 6, 1))
        paid.set_for(pnr)
        paid.save()
        # The hotel's booking paid in full.
        hof = trip.confirmations.get(confirmation_number="5305434791")
        hof.cost, hof.currency = D("240"), "EUR"
        hof.save()
        full = TripExpense(trip=trip, description="Hotel", amount=D("240"), currency="EUR", paid_by=bo,
                           category="lodging", spent_on=date(2027, 6, 2))
        full.set_for(hof)
        full.save()
        # No booking needed, with an estimate: paid on the day.
        entry = TripActivity.objects.get(trip=trip, title="Fuggerei entry")
        entry.no_booking, entry.est_cost, entry.currency, entry.cost_basis = True, D("8"), "EUR", "person"
        entry.save()
        # A foreign amount with no rate: left out of the totals, listed.
        d4 = trip.days.get(day_number=4)
        TripActivity.objects.create(trip=trip, day=d4, title="Swiss pass", est_cost=D("60"), currency="CHF")
        # An expense for nothing in particular (counts in its category's paid).
        TripExpense.objects.create(trip=trip, description="Snacks", amount=D("20"), currency="EUR", paid_by=ada,
                                   category="food", spent_on=date(2027, 9, 18))
        return trip

    def test_the_budget_version_matches_its_snapshot(self):
        trip = self.build()
        self.grant(trip)
        response, html = self.booklet(trip)
        self.assertTrue(response["Content-Disposition"].endswith('-booklet-budget.pdf"'))
        html = normalise(html)
        # No per-person table: the travellers are named on the cover and in the days, never next to money.
        page = html[html.index('<section class="budget-page">'):]
        for name in ("Ada", "Bo"):
            self.assertNotIn(name, page)
        if os.environ.get("UPDATE_SNAPSHOTS"):
            SNAPSHOT.write_text(html, encoding="utf-8")
            return
        expected = SNAPSHOT.read_text(encoding="utf-8")
        if html != expected:
            diff = "\n".join(list(difflib.unified_diff(expected.splitlines(), html.splitlines(), "snapshot", "now",
                                                       lineterm=""))[:60])
            self.fail("The budget booklet's HTML changed. If that's intended, rerun with UPDATE_SNAPSHOTS=1 and "
                      f"review the diff.\n{diff}")

    def test_what_the_budget_version_says(self):
        trip = self.build()
        self.grant(trip)
        _, html = self.booklet(trip)
        self.assertIn("Includes budget · as of August 15, 2027", html)
        self.assertIn("To pay: €500 (booked €900, paid €400)", html)
        self.assertIn('<p class="to-pay">Paid</p>', html)  # the hotel, on its check-in day
        self.assertIn("To pay there: ≈ €16", html)  # €8 per person × 2
        self.assertIn("Undecided: 1 choice, €190–€240, not in the totals.", html)
        self.assertIn("Not converted (no rate): Swiss pass (CHF 60)", html)
        self.assertIn("To pay there: ≈ CHF 60", html)  # its own currency, never converted

    def test_the_plain_booklet_has_none_of_it(self):
        trip = self.build()
        self.grant(trip)
        response, html = self.booklet(trip, budget=False)
        self.assertTrue(response["Content-Disposition"].endswith('-itinerary.pdf"'))
        for text in ("budget-page", "to-pay", "To pay", "Includes budget"):
            self.assertNotIn(text, html)


class ToPayTests(TestCase):
    """``budget_plan.to_pay`` on the booklet's own prefetch, through the view."""

    def setUp(self):
        self.user = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Bavaria", start_date=date(2027, 9, 20), end_date=date(2027, 9, 22),
                                        created_by=self.user, home_currency="EUR")
        TripGrant.objects.create(trip=self.trip, user=self.user, role=TripRole.EDITOR)
        self.ada, self.bo = Traveler.objects.create(name="Ada"), Traveler.objects.create(name="Bo")
        self.trip.travelers.set([self.ada, self.bo])
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 20))
        self.client.force_login(self.user)

    def leg(self, **fields):
        fields = {"currency": "EUR", "mode": "train", "operator": "DB", "origin": "Augsburg",
                  "destination": "Munich", "date": self.day.date, **fields}
        return TransportLeg.objects.create(trip=self.trip, **fields)

    def pay(self, amount, what, currency="EUR"):
        expense = TripExpense(trip=self.trip, description="x", amount=D(amount), currency=currency, paid_by=self.ada,
                              category="transport", spent_on=self.day.date)
        expense.set_for(what)
        expense.save()

    def lines(self):
        """{item label: to_pay} as the budget booklet sets them."""
        from apps.trips import views
        from apps.trips import options as option_groups
        trip = views._trip_page_queryset(self.user).get(pk=self.trip.pk)
        option_groups.attach(trip, list(trip.days.all()), self.user)
        views.itinerary.place_legs(trip)
        views._attach_confirmations(trip)
        budget_plan.attach_to_pay(trip, list(trip.expenses.all()))
        return {budget_plan._label(item): getattr(item, "to_pay", None)
                for item in budget_plan.planned_items(trip)}

    def test_part_paid_fully_paid_and_nothing_recorded(self):
        first, second = self.leg(origin="A", destination="B"), self.leg(origin="C", destination="D")
        third = self.leg(origin="E", destination="F")
        for leg, number, cost in ((first, "ONE", "96"), (second, "TWO", "50"), (third, "THREE", "30")):
            booking = Confirmation.objects.create(trip=self.trip, confirmation_number=number, cost=D(cost),
                                                  currency="EUR")
            booking.link(leg)
        self.pay("48", first)  # against the item: counts for its booking
        self.pay("50", Confirmation.objects.get(confirmation_number="TWO"))
        lines = self.lines()
        self.assertEqual(lines["A → B"], "To pay: €48 (booked €96, paid €48)")
        self.assertEqual(lines["C → D"], "Paid")
        self.assertEqual(lines["E → F"], "To pay: €30 (booked €30, nothing recorded as paid)")

    def test_one_booking_over_several_items_printed_once(self):
        legs = [self.leg(origin=f"X{n}", destination=f"Y{n}", order=n) for n in range(4)]
        booking = Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS", cost=D("120"),
                                              currency="EUR")
        for leg in legs:
            booking.link(leg)
        lines = self.lines()
        self.assertEqual(lines["X0 → Y0"], "To pay: €120 for 4 journeys (booked €120, nothing recorded as paid)")
        self.assertEqual([lines[f"X{n} → Y{n}"] for n in (1, 2, 3)], [None, None, None])

    def test_estimates_no_booking_needed_and_own_currency(self):
        self.leg(origin="A", destination="B", cost=D("24"), no_booking=True)
        self.leg(origin="C", destination="D", cost=D("90"), currency="CHF")
        unbooked = self.leg(origin="E", destination="F", cost=D("40"))
        self.pay("15", unbooked)
        Meal.objects.create(day=self.day, name="Augustiner", est_cost=D("30"), currency="EUR")
        self.leg(origin="G", destination="H")  # no estimate: the site doesn't know
        Confirmation.objects.create(trip=self.trip, confirmation_number="NOCOST").link(self.leg(origin="I",
                                                                                                destination="J"))
        lines = self.lines()
        self.assertEqual(lines["A → B"], "To pay there: ≈ €24")
        self.assertEqual(lines["C → D"], "To pay there: ≈ CHF 90")
        self.assertEqual(lines["E → F"], "To pay there: ≈ €25 (≈ €40, paid €15)")
        self.assertEqual(lines["Augustiner"], "To pay there: ≈ €60")
        self.assertIsNone(lines["G → H"])
        self.assertIsNone(lines["I → J"])  # booked, cost not on file

    def test_a_payment_in_another_currency_is_named_not_converted(self):
        booking = Confirmation.objects.create(trip=self.trip, confirmation_number="ONE", cost=D("100"),
                                              currency="EUR")
        booking.link(self.leg(origin="A", destination="B"))
        self.pay("20", booking, currency="USD")
        self.assertEqual(self.lines()["A → B"],
                         "To pay: €100 (booked €100, nothing recorded as paid) · also paid $20")

    def test_a_stay_on_its_check_in_day(self):
        Lodging.objects.create(trip=self.trip, name="Hotel", check_in=self.day.date, check_out=date(2027, 9, 22),
                               nightly_rate=D("95"), currency="EUR")
        _, html = Fixture.booklet(self, self.trip)
        self.assertIn('<p class="to-pay">To pay there: ≈ €190</p>', html)


class QueryAndAccessTests(ToPayTests):
    def one_of_each(self, tag):
        leg = self.leg(origin=f"A{tag}", destination=f"B{tag}", cost=D("10"))
        Meal.objects.create(day=self.day, name=f"Meal {tag}", est_cost=D("12"), currency="EUR")
        TripActivity.objects.create(trip=self.trip, day=self.day, title=f"Tour {tag}", est_cost=D("9"),
                                    currency="EUR")
        Lodging.objects.create(trip=self.trip, name=f"Inn {tag}", check_in=self.day.date,
                               check_out=date(2027, 9, 21), nightly_rate=D("50"), currency="EUR")
        booking = Confirmation.objects.create(trip=self.trip, confirmation_number=f"B{tag}", cost=D("10"),
                                              currency="EUR")
        booking.link(leg)
        self.pay("5", booking)

    def count(self, budget):
        url = reverse("trips:trip_pdf", args=[self.trip.pk]) + ("?budget=1" if budget else "")
        with mock.patch("apps.trips.pdf.render_pdf", return_value=b"%PDF"), \
                CaptureQueriesContext(connection) as ctx:
            self.client.get(url)
        return len(ctx.captured_queries)

    def test_a_fixed_number_of_queries_for_both_and_one_more_for_the_budget(self):
        warm_content_types()
        self.one_of_each("first")
        self.count(False), self.count(True)
        plain, budget = self.count(False), self.count(True)
        self.assertEqual(budget, plain + 1)  # the expenses; everything else is the booklet's own prefetch
        for n in range(3):
            self.one_of_each(n)
        self.assertEqual((self.count(False), self.count(True)), (plain, budget))

    def test_the_menu_offers_both_and_strangers_get_404(self):
        html = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        url = reverse("trips:trip_pdf", args=[self.trip.pk])
        self.assertIn(f'href="{url}" title="A printable booklet', html)
        self.assertIn(f'href="{url}?budget=1"', html)
        self.assertIn("data-pdf-budget>PDF with budget</a>", html)
        self.client.force_login(User.objects.create_user("st", "st@example.com", "pw-1234-abcd"))
        self.assertEqual(self.client.get(url + "?budget=1").status_code, 404)

    def test_a_viewer_may_download_it(self):
        viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        TripGrant.objects.create(trip=self.trip, user=viewer, role=TripRole.VIEWER)
        self.client.force_login(viewer)
        with mock.patch("apps.trips.pdf.render_pdf", return_value=b"%PDF"):
            self.assertEqual(self.client.get(reverse("trips:trip_pdf", args=[self.trip.pk]) + "?budget=1")
                             .status_code, 200)
