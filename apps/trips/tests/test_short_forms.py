"""Short trip-item forms (docs/plans/short-forms.md, F1): the journey, stay, activity, meal and choice-option forms
show what's needed up front and fold the rest under **More details** (``forms.MoreDetailsMixin``). The fold stays
closed, its summary lists what's filled, and it opens by itself only on an error. Travellers and the cost amount
never fold; Cost is / People / Rooms do, and the preview reads them from the item's scope."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.trips.models import (
    Day,
    Lodging,
    Meal,
    Option,
    OptionGroup,
    TransportLeg,
    Traveler,
    Trip,
    TripActivity,
    TripGrant,
    TripRole,
)

User = get_user_model()


def split(html):
    """(before the first More details fold, the fold itself)."""
    start = html.index("data-more-details")
    start = html.rindex("<details", 0, start)
    return html[:start], html[start : html.index("</details>", start)]


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(
            name="Bavaria", start_date=date(2027, 9, 20), end_date=date(2027, 9, 23), created_by=self.editor
        )
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        self.trip.travelers.set([Traveler.objects.create(name="Ada"), Traveler.objects.create(name="Bo")])
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 20))
        self.leg = TransportLeg.objects.create(
            trip=self.trip, mode="train", origin="Augsburg", destination="Munich", date=self.day.date
        )
        self.stay = Lodging.objects.create(
            trip=self.trip, name="Hotel Laimer Hof", check_in=date(2027, 9, 20), check_out=date(2027, 9, 22)
        )
        self.activity = TripActivity.objects.create(trip=self.trip, day=self.day, title="Castle tour", kind="tour")
        self.meal = Meal.objects.create(day=self.day, name="Augustiner", meal_type="dinner")
        self.group = OptionGroup.objects.create(trip=self.trip, day=self.day, prompt="Where to stay?", kind="stay")
        Option.objects.create(group=self.group, title="Ibis", est_cost=Decimal("95"))
        self.client.force_login(self.editor)

    def urls(self):
        return {
            "leg": reverse("trips:leg_edit", args=[self.trip.pk, self.leg.pk]),
            "stay": reverse("trips:stay_edit", args=[self.trip.pk, self.stay.pk]),
            "activity": reverse("trips:activity_edit", args=[self.trip.pk, self.day.pk, self.activity.pk]),
            "meal": reverse("trips:meal_edit", args=[self.trip.pk, self.day.pk, self.meal.pk]),
            "choice": reverse("trips:group_edit", args=[self.trip.pk, self.group.pk]),
        }

    def get(self, kind):
        return self.client.get(self.urls()[kind]).content.decode()


class LayoutTests(Fixture):
    UP_FRONT = {
        "leg": [
            "origin",
            "destination",
            "mode",
            "date",
            "departure_local",
            "duration_minutes",
            "arrival_local",
            "operator",
            "cost",
        ],
        "stay": ["name", "city", "address", "check_in", "check_out", "nightly_rate", "currency"],
        "activity": ["kind", "title", "start_time", "end_time", "travelers", "est_cost", "currency"],
        "meal": ["name", "meal_type", "reserved_time", "est_cost", "currency"],
        "choice": ["options-0-title", "options-0-est_cost"],
    }
    FOLDED = {
        "leg": ["origin_timezone", "destination_timezone", "est_duration", "cost_basis", "cost_people", "notes"],
        "stay": ["cost_basis", "cost_people", "rooms", "notes", "no_booking", "latitude", "longitude"],
        "activity": ["provider", "cost_basis", "cost_people", "notes", "no_booking", "order"],
        "meal": ["cuisine", "price_range", "why_recommended", "reservation_notes", "cost_basis", "order"],
        "choice": ["options-0-notes", "options-0-url", "options-0-nights", "options-0-cost_basis"],
    }

    def test_each_page_has_the_short_form_then_the_fold(self):
        for kind in self.UP_FRONT:
            with self.subTest(kind):
                before, fold = split(self.get(kind))
                for name in self.UP_FRONT[kind]:
                    self.assertIn(f'name="{name}"', before, name)
                    self.assertNotIn(f'name="{name}"', fold, name)
                for name in self.FOLDED[kind]:
                    self.assertIn(f'name="{name}"', fold, name)
                self.assertNotIn(" open>", fold[: fold.index(">") + 1])  # closed

    def test_the_cost_preview_stays_up_front_and_reads_its_scope(self):
        for kind in ("leg", "stay", "activity", "meal"):
            before, fold = split(self.get(kind))
            self.assertIn("data-cost-preview", before)
            self.assertIn("data-cost-split", before)
            self.assertIn("data-cost-more", fold)
        self.assertIn("data-option-form data-cost-scope", self.get("choice"))

    def test_the_stay_pin_moved_into_the_fold(self):
        html = self.get("stay")
        self.assertNotIn("data-adjust-pin", html)
        self.assertIn("Found from the address.", split(html)[1])

    def test_the_return_trip_is_its_own_closed_fold(self):
        html = self.get("leg")
        start = html.index("data-return-trip")
        self.assertIn('name="add_return"', html[start:])
        self.assertNotIn("open", html[start : html.index(">", start)])
        self.assertNotIn('name="add_return"', split(html)[1])


class SummaryTests(Fixture):
    def test_it_lists_what_is_filled_and_stays_closed(self):
        self.activity.provider = "Bus tours"
        self.activity.notes = "Bring water"
        self.activity.save()
        before, fold = split(self.get("activity"))
        self.assertIn(": provider, notes</span>", fold)
        self.assertNotIn(" open>", fold[: fold.index(">") + 1])

    def test_more_than_three_shows_a_count(self):
        self.meal.cuisine, self.meal.price_range = "Bavarian", "$$"
        self.meal.why_recommended, self.meal.reservation_notes = "Beer hall", "Ask for the garden"
        self.meal.save()
        self.assertRegex(split(self.get("meal"))[1], r": cuisine, price range, 2 more</span>")

    def test_nothing_filled_no_summary(self):
        self.assertNotIn("data-more-summary", split(self.get("activity"))[1])

    def test_an_error_inside_opens_it(self):
        url = self.urls()["activity"]
        form = self.client.get(url).context["form"]
        data = {name: form[name].value() for name in form.fields if form[name].value() is not None}
        data.update(travelers=[], order="not a number", next=url)
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        fold = split(response.content.decode())[1]
        self.assertIn(" open>", fold[: fold.index(">") + 1])


class SavingTests(Fixture):
    def test_folded_fields_save(self):
        url = self.urls()["stay"]
        form = self.client.get(url).context["form"]
        data = {name: form[name].value() for name in form.fields if form[name].value() is not None}
        data.update(notes="Late check-in", no_booking="on", cost_basis="room_night", rooms=2, nightly_rate="95")
        data.pop("option", None)
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
        self.stay.refresh_from_db()
        self.assertEqual(
            (self.stay.notes, self.stay.no_booking, self.stay.cost_basis, self.stay.rooms),
            ("Late check-in", True, "room_night", 2),
        )


class EmptyListTests(Fixture):
    def test_a_stay_choice_page_opens_on_a_trip_with_no_cities(self):
        """``share_choices`` keyed each select by its SQL, which an empty list (no trip cities yet) can't print:
        the choice page was a 500."""
        self.assertFalse(self.trip.cities.exists())
        self.assertEqual(self.client.get(self.urls()["choice"]).status_code, 200)
