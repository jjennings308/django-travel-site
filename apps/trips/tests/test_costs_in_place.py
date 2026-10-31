"""Costs where you plan, and payments against what they paid for (docs/plans/budget-estimates.md, B3): the note on
each row of a day, per person and cheapest in a choice, an expense's For, paid per Plan row, Record a payment."""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.trips.forms import TripExpenseForm
from apps.trips.models import (Confirmation, Day, Lodging, Meal, Option, OptionGroup, TransportLeg, Traveler, Trip,
                               TripExpense, TripGrant, TripRole)

User = get_user_model()
D = Decimal


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        from apps.accounts.models import AccountSettings
        AccountSettings.objects.update_or_create(user=self.editor, defaults={"preferred_currency": "EUR"})
        self.trip = Trip.objects.create(name="Bavaria", start_date=date(2027, 9, 20), end_date=date(2027, 9, 22),
                                        created_by=self.editor, home_currency="EUR")
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        self.ada, self.bo = Traveler.objects.create(name="Ada"), Traveler.objects.create(name="Bo")
        self.trip.travelers.set([self.ada, self.bo])
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 20))
        self.client.force_login(self.editor)

    def leg(self, **fields):
        fields.setdefault("currency", "EUR")
        return TransportLeg.objects.create(trip=self.trip, mode="train", operator="DB", origin="Augsburg",
                                           destination="Munich", date=self.day.date, **fields)

    def page(self):
        return self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()


class DayRowTests(Fixture):
    def test_estimates_and_bookings_show_quietly_on_their_rows(self):
        self.leg(cost=D("24"))
        Lodging.objects.create(trip=self.trip, name="Hotel", check_in=self.day.date, check_out=date(2027, 9, 22),
                               nightly_rate=D("95"), currency="EUR", cost_basis="room_night", rooms=1)
        Meal.objects.create(day=self.day, name="Augustiner", est_cost=D("30"), currency="EUR")  # a food idea
        Meal.objects.create(day=self.day, name="Hofbräuhaus", est_cost=D("40"), currency="EUR",
                            reserved_time="19:00")  # a booked table, in the timeline
        html = self.page()
        self.assertIn("data-cost-note>≈ €12 pp</span>", html)  # 24 total for 2
        self.assertIn("data-cost-note>≈ €95 pp</p>", html)  # 95 × 1 room × 2 nights for 2
        self.assertIn("data-cost-note>≈ €30 pp</p>", html)
        self.assertIn("data-cost-note>≈ €40 pp</span>", html)

    def test_a_booking_replaces_the_estimate(self):
        legs = [self.leg(cost=D("24")), self.leg(cost=D("24"))]
        booking = Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS", cost=D("40"), currency="EUR")
        booking.link(legs[0])
        html = self.page()
        self.assertIn("data-cost-note>€40 · booked</span>", html)
        booking.link(legs[1])
        self.assertEqual(self.page().count("data-cost-note>€40 for 2 · booked</span>"), 2)


class ChoiceTests(Fixture):
    def test_per_person_and_the_cheapest(self):
        group = OptionGroup.objects.create(trip=self.trip, day=self.day, prompt="Where to stay", kind="stay", nights=2)
        Option.objects.create(group=group, title="Hotel", est_cost=D("95"), currency="EUR", cost_basis="room_night",
                              rooms=2)  # 380 → 190 pp
        Option.objects.create(group=group, title="Flat", est_cost=D("150"), currency="EUR")  # 300 → 150 pp
        html = self.page()
        self.assertIn("EUR 380.00 · EUR 190.00 pp", html)
        self.assertIn("EUR 300.00 · EUR 150.00 pp", html)
        self.assertIn("data-cheapest>Cheapest per person: <strong>Flat</strong>", html)

    def test_no_cheapest_for_different_people(self):
        group = OptionGroup.objects.create(trip=self.trip, day=self.day, prompt="Afternoon", kind="do")
        Option.objects.create(group=group, title="Castle", est_cost=D("20"), currency="EUR")
        Option.objects.create(group=group, title="Museum", est_cost=D("10"), currency="EUR", cost_people=1)
        self.assertNotIn("data-cheapest", self.page())


class ExpenseForTests(Fixture):
    def data(self, **over):
        values = {"description": "Train", "category": "transport", "amount": "40", "currency": "EUR",
                  "spent_on": "2027-09-01", "day": "", "paid_by": self.ada.pk, "notes": ""}
        values.update(over)
        return values

    def test_for_a_booking_or_an_item_of_this_trip_only(self):
        leg = self.leg()
        booking = Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS", cost=D("40"), currency="EUR")
        form = TripExpenseForm(self.data(paid_for=f"confirmation-{booking.pk}"), trip=self.trip,
                               instance=TripExpense(trip=self.trip))
        self.assertTrue(form.is_valid(), form.errors)
        expense = form.save()
        self.assertEqual((expense.paid_for, expense.for_label), (booking, "GCH7JS"))
        again = TripExpenseForm(instance=expense, trip=self.trip)
        self.assertEqual(again.initial["paid_for"], f"confirmation-{booking.pk}")
        other = Trip.objects.create(name="Other", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        theirs = TransportLeg.objects.create(trip=other, origin="X", destination="Y", date=date(2027, 1, 1))
        refused = TripExpenseForm(self.data(paid_for=f"leg-{theirs.pk}"), trip=self.trip,
                                  instance=TripExpense(trip=self.trip))
        self.assertFalse(refused.is_valid())
        self.assertIn("paid_for", refused.errors)
        with self.assertRaises(ValueError):
            TripExpense(trip=self.trip).set_for(theirs)
        expense.set_for(leg)
        self.assertEqual(expense.for_label, "Augsburg → Munich")

    def test_paid_per_row_and_record_a_payment(self):
        legs = [self.leg(cost=D("24")), self.leg(cost=D("24"))]
        booking = Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS", cost=D("40"), currency="EUR")
        for leg in legs:
            booking.link(leg)
        budget = reverse("trips:trip_budget", args=[self.trip.pk])
        html = self.client.get(budget).content.decode()
        self.assertIn(f'href="?pay=confirmation-{booking.pk}&amp;in=EUR#add-cost" data-record-payment>', html)
        form = self.client.get(budget + f"?pay=confirmation-{booking.pk}").context["form"]
        self.assertEqual((form.initial["description"], form.initial["amount"], form.initial["category"],
                          form.initial["paid_for"]),
                         ("GCH7JS · 2 journeys", D("40"), "transport", f"confirmation-{booking.pk}"))
        # Paid against one of the booking's legs counts on the booking's row.
        TripExpense.objects.create(trip=self.trip, description="Deposit", amount=D("15"), currency="EUR",
                                   paid_by=self.ada, category="transport")  # for nothing in particular
        expense = TripExpense(trip=self.trip, description="Train", amount=D("25"), currency="EUR", paid_by=self.bo,
                              category="transport")
        expense.set_for(legs[1])
        expense.save()
        plan = self.client.get(budget).context["plan"]
        row = plan["categories"][0]["rows"][0]
        self.assertEqual((row["label"], row["paid"]), ("GCH7JS · 2 journeys", D("25.00")))
        self.assertEqual(plan["categories"][0]["paid"], D("40.00"))  # the category counts both, as before
        self.assertIn("· for Augsburg → Munich", self.client.get(budget).content.decode())  # the Spent list
