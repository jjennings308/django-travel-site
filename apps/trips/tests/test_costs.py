"""What a cost means (docs/plans/budget-estimates.md, B1): every item's estimate with its basis, people and nights
(apps/trips/costs.py), the trip's planned total without the old double count, choices and Pick, the forms."""
from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.trips import costs
from apps.trips.forms import LegEditForm, LodgingForm, MealForm, OptionForm, TripActivityForm
from apps.trips.models import (Confirmation, Day, Lodging, Meal, Option, OptionGroup, TransportLeg, Traveler, Trip,
                               TripActivity, TripChange, TripGrant, TripRole)

User = get_user_model()
D = Decimal


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Bavaria", start_date=date(2027, 9, 20), end_date=date(2027, 9, 25),
                                        created_by=self.editor, home_currency="EUR")
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        self.people = [Traveler.objects.create(name=n) for n in ("Ada", "Bo", "Cy", "Di", "Ed", "Flo")]
        self.trip.travelers.set(self.people)
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 20))

    def stay(self, nights=4, **fields):
        return Lodging.objects.create(trip=self.trip, name="Hotel Augusta", check_in=date(2027, 9, 20),
                                      check_out=date(2027, 9, 20 + nights), currency="EUR", **fields)

    def leg(self, **fields):
        return TransportLeg.objects.create(trip=self.trip, origin="Augsburg", destination="Munich",
                                           date=date(2027, 9, 20), currency="EUR", **fields)

    def line(self, item):
        return costs.estimate(item, self.day, self.trip).line


class BasisTests(Fixture):
    def test_stays(self):
        self.assertEqual(self.line(self.stay(nightly_rate=D("95"), cost_basis="room_night", rooms=3)),
                         "€95 per room per night × 3 rooms × 4 nights = €1,140 · €190 each (6)")
        vrbo = self.stay(nightly_rate=D("310"))  # blank basis: per night, as nightly_rate always meant
        cost = costs.estimate(vrbo, self.day, self.trip)
        self.assertEqual(cost.line, "€310 per night × 4 nights = €1,240 · €206.67 each (6)")
        self.assertEqual((cost.basis, cost.total, cost.per_person), ("night", D("1240"), D("206.67")))
        self.assertEqual(self.line(self.stay(nightly_rate=D("40"), cost_basis="person_night")),
                         "€40 per person per night × 6 × 4 nights = €960 · €160 each (6)")
        self.assertEqual(self.line(self.stay(nightly_rate=D("900"), cost_basis="total")), "€900 total · €150 each (6)")

    def test_legs_activities_meals(self):
        self.assertEqual(self.line(self.leg(cost=D("62"), cost_people=4)), "€62 total · €15.50 each (4)")
        self.assertEqual(self.line(self.leg(cost=D("12"), cost_basis="person")), "€12 per person × 6 = €72")
        museum = TripActivity.objects.create(trip=self.trip, day=self.day, title="Castle museum", est_cost=D("8"),
                                             currency="EUR", cost_basis="person")
        self.assertEqual(self.line(museum), "€8 per person × 6 = €48")
        lunch = Meal.objects.create(day=self.day, name="Lunch", est_cost=D("15"), currency="EUR")  # per person
        self.assertEqual(self.line(lunch), "€15 per person × 6 = €90")

    def test_a_basis_the_kind_doesnt_offer_falls_back_to_its_default(self):
        leg = self.leg(cost=D("50"), cost_basis="room_night")
        self.assertEqual(costs.basis_of(leg), "total")


class PeopleAndNightsTests(Fixture):
    def test_from_own_travellers_then_the_roster_then_the_trip_then_the_override(self):
        tour = TripActivity.objects.create(trip=self.trip, day=self.day, title="Tour", est_cost=D("20"),
                                           currency="EUR", cost_basis="person")
        tour.travelers.set(self.people[:2])
        self.assertEqual(costs.people_for(tour, self.day, self.trip), (2, True))
        self.day.travelers.set(self.people[:3])
        lunch = Meal.objects.create(day=self.day, name="Lunch", est_cost=D("10"), currency="EUR")
        self.assertEqual(costs.people_for(lunch, self.day, self.trip), (3, True))
        self.assertEqual(costs.people_for(lunch, None, self.trip), (6, True))
        lunch.cost_people = 5
        self.assertEqual(costs.people_for(lunch, self.day, self.trip), (5, True))

    def test_unknown_people_gives_no_share(self):
        self.trip.travelers.clear()
        leg = self.leg(cost=D("62"))
        cost = costs.estimate(leg, None, self.trip)
        self.assertEqual((cost.total, cost.per_person, cost.line), (D("62"), None, "€62 total · people not set"))
        per_person = costs.estimate(self.leg(cost=D("8"), cost_basis="person"), None, self.trip)
        self.assertEqual((per_person.total, per_person.line), (None, "€8 per person · people not set"))

    def test_nights_from_a_stay_and_a_stay_option(self):
        self.assertEqual(costs.nights_for(self.stay(nights=3)), 3)
        group = OptionGroup.objects.create(trip=self.trip, day=self.day, prompt="Where to stay", kind="stay", nights=2)
        option = Option.objects.create(group=group, title="Flat", est_cost=D("80"), currency="EUR")
        self.assertEqual(costs.nights_for(option), 2)
        option.nights = 3
        self.assertEqual(costs.nights_for(option), 3)
        unknown = Lodging(trip=self.trip, name="x", check_in=date(2027, 9, 20), nightly_rate=D("95"), currency="EUR")
        self.assertEqual(costs.estimate(unknown, self.day, self.trip).line, "€95 per night × ? nights")

    def test_cents_remainder_rides_on_the_first_share(self):
        cost = costs.estimate(self.leg(cost=D("100"), cost_people=3), None, self.trip)
        self.assertEqual(cost.per_person, D("33.34"))  # 33.34 + 33.33 + 33.33

    def test_other_currencies_and_whole_amounts(self):
        self.assertEqual(costs.money(D("1140"), "EUR"), "€1,140")
        self.assertEqual(costs.money(D("15.5"), "USD"), "$15.50")
        self.assertEqual(costs.money(D("12"), "NOK"), "NOK 12")


class PlannedTotalTests(Fixture):
    def page_estimate(self):
        from apps.accounts.models import AccountSettings
        AccountSettings.objects.update_or_create(user=self.editor, defaults={"preferred_currency": "EUR"})
        self.client.force_login(self.editor)
        return self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).context["cost_estimate"]

    def test_a_confirmation_counts_once_across_its_legs_and_their_estimates_step_aside(self):
        legs = [self.leg(cost=D("100")) for _ in range(4)]
        booking = Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS", cost=D("380"),
                                              currency="EUR")
        for leg in legs:
            booking.link(leg)
        self.leg(cost=D("50"))  # not booked: its estimate counts
        estimate = self.page_estimate()
        self.assertEqual((estimate["total"], estimate["bookings"], estimate["estimates"]), (D("430.00"), 1, 1))

    def test_an_activity_with_a_booking_isnt_counted_twice(self):
        tour = TripActivity.objects.create(trip=self.trip, day=self.day, title="Tour", est_cost=D("40"), currency="EUR")
        booking = Confirmation.objects.create(trip=self.trip, confirmation_number="T1", cost=D("45"), currency="EUR")
        booking.link(tour)
        self.assertEqual(self.page_estimate()["total"], D("45.00"))  # was 85 before B1

    def test_stays_and_meals_count_now(self):
        self.stay(nightly_rate=D("95"), cost_basis="room_night", rooms=3)
        Meal.objects.create(day=self.day, name="Dinner", est_cost=D("30"), currency="EUR")
        self.assertEqual(self.page_estimate()["total"], D("1320.00"))  # 1,140 + 30 × 6

    def test_an_estimate_without_a_total_is_counted_as_unpriced(self):
        self.stay(nightly_rate=D("95"), cost_basis="room_night")  # no rooms: no total yet
        self.leg(cost=D("50"))
        estimate = self.page_estimate()
        self.assertEqual((estimate["total"], estimate["estimates"], estimate["unpriced"]), (D("50.00"), 1, 1))


class ChoiceTests(Fixture):
    def setUp(self):
        super().setUp()
        self.group = OptionGroup.objects.create(trip=self.trip, day=self.day, prompt="Where to stay", kind="stay",
                                                nights=4)

    def test_old_options_read_as_before_and_new_bases_read_as_costs(self):
        old = Option.objects.create(group=self.group, title="Flat", est_cost=D("80"), currency="EUR")
        self.assertEqual(old.kind_line(), "EUR 80.00/night × 4 = EUR 320.00")  # the booklet's wording, unchanged
        self.assertEqual(old.own_cost, D("320"))
        rooms = Option.objects.create(group=self.group, title="Hotel", est_cost=D("95"), currency="EUR",
                                      cost_basis="room_night", rooms=3)
        rooms._people = (6, True)
        self.assertEqual(rooms.kind_line(), "€95 per room per night × 3 rooms × 4 nights = €1,140 · €190 each (6)")
        self.assertEqual(rooms.own_cost, D("1140"))

    def test_pick_carries_the_basis_rooms_and_people(self):
        from apps.trips.options import make_item
        option = Option.objects.create(group=self.group, title="Hotel", est_cost=D("95"), currency="EUR",
                                       cost_basis="room_night", rooms=3, cost_people=5)
        self.group.pick(option)
        stay = make_item(option)
        self.assertEqual((stay.nightly_rate, stay.cost_basis, stay.rooms, stay.cost_people),
                         (D("95"), "room_night", 3, 5))
        eat = OptionGroup.objects.create(trip=self.trip, day=self.day, prompt="Dinner", kind="eat", meal_type="dinner")
        menu = Option.objects.create(group=eat, title="Augustiner", est_cost=D("120"), currency="EUR")
        eat.pick(menu)
        meal = make_item(menu)
        self.assertEqual((meal.est_cost, meal.cost_basis), (D("120"), "total"))  # not read per person


class FormTests(Fixture):
    def test_each_kind_offers_its_bases_and_refuses_others(self):
        stay = self.stay()
        form = LodgingForm({"name": "Hotel", "check_in": "2027-09-20", "check_out": "2027-09-24",
                            "nightly_rate": "95", "currency": "EUR", "cost_basis": "person"}, instance=stay)
        self.assertFalse(form.is_valid())
        self.assertIn("cost_basis", form.errors)
        leg_basis = [v for v, _ in LegEditForm(instance=self.leg()).fields["cost_basis"].choices]
        self.assertEqual(leg_basis, ["", "total", "person"])
        activity = TripActivity.objects.create(trip=self.trip, day=self.day, title="Tour")
        self.assertNotIn("rooms", TripActivityForm(instance=activity, trip=self.trip).fields)
        meal_basis = [v for v, _ in MealForm(instance=Meal(day=self.day)).fields["cost_basis"].choices]
        self.assertEqual(meal_basis, ["", "person", "total"])

    def test_rooms_only_with_per_room_per_night(self):
        stay = self.stay()
        data = {"name": "Hotel", "check_in": "2027-09-20", "check_out": "2027-09-24", "nightly_rate": "95",
                "currency": "EUR", "cost_basis": "night", "rooms": "3"}
        form = LodgingForm(data, instance=stay)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.save().rooms)
        form = LodgingForm({**data, "cost_basis": "room_night"}, instance=stay)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().rooms, 3)

    def test_the_stay_page_draws_the_cost_block(self):
        stay = self.stay(nightly_rate=D("95"))
        self.client.force_login(self.editor)
        html = self.client.get(reverse("trips:stay_edit", args=[self.trip.pk, stay.pk])).content.decode()
        self.assertIn("data-cost-fields", html)
        self.assertIn('data-nights="4"', html)
        self.assertIn('data-people="6"', html)
        self.assertEqual(html.count('name="cost_basis"'), 1)
        self.assertIn('data-cost-rooms', html)

    def test_the_return_trip_copies_basis_and_people_not_the_amount(self):
        from apps.trips.forms import TransportLegForm
        leg = self.leg(cost=D("12"), cost_basis="person", cost_people=4)
        form = TransportLegForm({"mode": "train", "origin": "Augsburg", "destination": "Munich", "date": "2027-09-20",
                                 "origin_timezone": "Europe/Berlin", "destination_timezone": "Europe/Berlin",
                                 "currency": "EUR", "cost": "12", "cost_basis": "person", "cost_people": "4",
                                 "add_return": "on", "return_date": "2027-09-22"}, instance=leg)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        back = form.return_leg
        self.assertEqual((back.cost, back.cost_basis, back.cost_people), (None, "person", 4))


class HistoryTests(Fixture):
    def test_a_basis_change_is_one_cost_line(self):
        stay = self.stay(nightly_rate=D("95"))
        stay.cost_basis, stay.rooms = "room_night", 3
        stay.save()
        change = TripChange.objects.filter(trip=self.trip).latest("pk")
        self.assertEqual(change.summary.count("cost "), 1)
        self.assertIn("cost €95 per night → €95 per room per night × 3 rooms", change.summary)

    def test_meals_show_their_cost(self):
        meal = Meal.objects.create(day=self.day, name="Lunch", reserved_time=time(12))
        meal.est_cost, meal.currency = D("15"), "EUR"
        meal.save()
        self.assertIn("cost none → €15 per person", TripChange.objects.filter(trip=self.trip).latest("pk").summary)
