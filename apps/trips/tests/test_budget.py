"""Trip expenses: equal splits in cents, balances, settle-up, and who may do what."""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.trips.budget import settle, shares, summarize
from apps.trips.models import Traveler, Trip, TripExpense, TripGrant, TripRole

User = get_user_model()


class BudgetFixture(TestCase):
    def setUp(self):
        self.trip = Trip.objects.create(name="Rome", start_date=date(2027, 4, 1), end_date=date(2027, 4, 8))
        self.james = Traveler.objects.create(name="James")
        self.regan = Traveler.objects.create(name="Regan")
        self.sara = Traveler.objects.create(name="Sara")
        self.trip.travelers.add(self.james, self.regan, self.sara)

    def cost(self, amount, paid_by, shared=(), currency="EUR", **kw):
        expense = TripExpense.objects.create(trip=self.trip, description=kw.pop("description", "x"), amount=Decimal(amount),
                                             currency=currency, paid_by=paid_by, **kw)
        expense.shared_with.set(shared)
        return expense


class ArithmeticTests(BudgetFixture):
    def test_equal_split_puts_remainder_cents_on_the_payer(self):
        split = shares(Decimal("100.00"), self.james, [self.james, self.regan, self.sara])
        self.assertEqual(sum(split.values()), 10000)
        self.assertEqual(split[self.james], 3334)  # payer absorbs the odd cent
        self.assertEqual((split[self.regan], split[self.sara]), (3333, 3333))

    def test_settle_up_three_people(self):
        self.cost("90.00", self.james)                                  # dinner for all three
        self.cost("30.00", self.regan, shared=[self.regan, self.sara])  # taxi for two
        s = summarize(TripExpense.objects.all(), [self.james, self.regan, self.sara])["EUR"]
        self.assertEqual(s["total"], Decimal("120.00"))
        balances = {p.name: b for p, _paid, _share, b in s["people"]}
        self.assertEqual(balances, {"James": Decimal("60.00"), "Regan": Decimal("-15.00"), "Sara": Decimal("-45.00")})
        self.assertEqual([(d.name, c.name, a) for d, c, a in s["transfers"]],
                         [("Sara", "James", Decimal("45.00")), ("Regan", "James", Decimal("15.00"))])

    def test_currencies_are_kept_apart(self):
        self.cost("100.00", self.james, currency="EUR")
        self.cost("50.00", self.regan, currency="usd")
        summary = summarize(TripExpense.objects.all(), [self.james, self.regan, self.sara])
        self.assertEqual(sorted(summary), ["EUR", "USD"])
        self.assertEqual(summary["USD"]["total"], Decimal("50.00"))

    def test_settle_balances_to_zero(self):
        self.assertEqual(settle({self.james: 0, self.regan: 0}), [])


class BudgetPageTests(BudgetFixture):
    def setUp(self):
        super().setUp()
        self.viewer = User.objects.create_user("viewer", "v@example.com", "pw-1234-abcd")
        self.editor = User.objects.create_user("editor", "e@example.com", "pw-1234-abcd")
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        self.url = reverse("trips:trip_budget", args=[self.trip.pk])

    def test_viewer_sees_but_cannot_add(self):
        self.cost("90.00", self.james, description="Dinner")
        self.client.force_login(self.viewer)
        page = self.client.get(self.url)
        self.assertContains(page, "Dinner")
        self.assertContains(page, "pays <strong>James</strong>")
        self.assertNotContains(page, "Add a cost")
        self.assertEqual(self.client.post(self.url, {"description": "x"}).status_code, 403)

    def test_editor_adds_edits_and_removes(self):
        self.client.force_login(self.editor)
        response = self.client.post(self.url, {"description": "Colosseum tickets", "category": "activities",
                                               "amount": "54.00", "currency": "eur", "spent_on": "2027-04-02",
                                               "paid_by": self.regan.pk})
        self.assertRedirects(response, self.url)
        expense = TripExpense.objects.get()
        self.assertEqual((expense.currency, expense.created_by, expense.paid_by), ("EUR", self.editor, self.regan))
        edit = reverse("trips:expense_edit", args=[self.trip.pk, expense.pk])
        self.client.post(edit, {"description": "Colosseum", "category": "activities", "amount": "60.00",
                                "currency": "EUR", "paid_by": self.regan.pk})
        expense.refresh_from_db()
        self.assertEqual(expense.amount, Decimal("60.00"))
        self.client.post(edit, {"delete": "1"})
        self.assertFalse(TripExpense.objects.exists())

    def test_payer_must_be_on_the_trip(self):
        stranger = Traveler.objects.create(name="Stranger")
        self.client.force_login(self.editor)
        response = self.client.post(self.url, {"description": "x", "category": "other", "amount": "1",
                                               "currency": "EUR", "paid_by": stranger.pk})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(TripExpense.objects.exists())

    def test_no_grant_is_404_and_public_page_has_no_costs(self):
        self.cost("90.00", self.james, description="Secret dinner")
        self.client.force_login(User.objects.create_user("x", "x@example.com", "pw-1234-abcd"))
        self.assertEqual(self.client.get(self.url).status_code, 404)
        token = self.trip.enable_public()
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("public_trip", args=[token])), "Secret dinner")


class FormFieldsRenderTests(BudgetFixture):
    """The shared trips/_form_fields.html must render fields when no hide_fields is passed
    (it rendered none: the day, section and cost forms were empty)."""

    def test_day_and_budget_forms_show_their_fields(self):
        from apps.trips.models import Day
        editor = User.objects.create_user("editor", "e@example.com", "pw-1234-abcd")
        TripGrant.objects.create(trip=self.trip, user=editor, role=TripRole.EDITOR)
        day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 4, 1))
        self.client.force_login(editor)
        day_page = self.client.get(reverse("trips:day_edit", args=[self.trip.pk, day.pk]))
        for name in ("day_number", "theme", "city"):
            self.assertContains(day_page, f'name="{name}"')
        budget = self.client.get(reverse("trips:trip_budget", args=[self.trip.pk]))
        for name in ("description", "amount", "paid_by", "shared_with"):
            self.assertContains(budget, f'name="{name}"')
