"""Typed choices T2 (docs/plans/typed-choices.md): picking an option of a typed choice makes the real stay,
meal, activity or journey on the day, inside the option, once."""
from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import City, Country, POI
from apps.trips import changes, options
from apps.trips.models import (Day, Lodging, Meal, Option, OptionGroup, Traveler, TransportLeg, Trip, TripActivity,
                               TripChange, TripGrant, TripRole, counts_q)

User = get_user_model()
APPROVED = ApprovalStatus.APPROVED


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Bavaria", start_date=date(2027, 9, 18), end_date=date(2027, 9, 24),
                                        created_by=self.editor, home_currency="EUR")
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        de = Country.objects.create(name="Germany", slug="de", iso_code="DE", iso3_code="DEU", continent="Europe",
                                    approval_status=APPROVED, currency_code="EUR")
        self.augsburg = City.objects.create(name="Augsburg", slug="augsburg", country=de, latitude=48.4,
                                            longitude=10.9, approval_status=APPROVED, timezone="Europe/Berlin")
        self.munich = City.objects.create(name="Munich", slug="munich", country=de, latitude=48.1, longitude=11.6,
                                          approval_status=APPROVED, timezone="Europe/Berlin")
        self.trip.cities.set([self.augsburg, self.munich])
        self.keller = POI.objects.create(name="Augustiner Keller", slug="augustiner", city=self.munich, latitude=48,
                                         longitude=11, approval_status=APPROVED, poi_type_id="food")
        self.days = [Day.objects.create(trip=self.trip, day_number=n, date=date(2027, 9, 17 + n), city=self.augsburg)
                     for n in range(1, 6)]
        self.day = self.days[1]

    def choice(self, kind, **extra):
        return OptionGroup.objects.create(trip=self.trip, day=self.day, prompt=f"A {kind}", kind=kind, **extra)

    def pick(self, option, fetch=False):
        self.client.force_login(self.editor)
        headers = {"HTTP_X_REQUESTED_WITH": "fetch"} if fetch else {}
        return self.client.post(reverse("trips:option_pick", args=[self.trip.pk, option.pk]), **headers)


class MakeTests(Fixture):
    def test_a_stay_from_the_day_for_its_nights(self):
        group = self.choice("stay", nights=3)
        rugs = Option.objects.create(group=group, title="Rugs Hotel", est_cost=Decimal("95"), currency="EUR",
                                     place_text="Maximilianstraße 1", city=self.augsburg, notes="Quiet rooms",
                                     url="https://example.com/rugs")
        response = self.pick(rugs)
        stay = Lodging.objects.get()
        self.assertEqual((stay.name, stay.address, stay.city, stay.check_in, stay.check_out, stay.nightly_rate,
                          stay.currency, stay.option),
                         ("Rugs Hotel", "Maximilianstraße 1", self.augsburg, date(2027, 9, 19), date(2027, 9, 22),
                          Decimal("95"), "EUR", rugs))
        self.assertEqual(stay.notes, "Quiet rooms\nhttps://example.com/rugs")
        rugs.refresh_from_db()
        self.assertEqual(rugs.made, stay)
        self.assertRedirects(response, reverse("trips:trip_detail", args=[self.trip.pk])
                             + f"?item=stay-{stay.pk}#stay-{stay.pk}", fetch_redirect_response=False)

    def test_an_options_own_nights_win(self):
        group = self.choice("stay", nights=2)
        flat = Option.objects.create(group=group, title="Flat", nights=4)
        self.pick(flat)
        self.assertEqual(Lodging.objects.get().check_out, date(2027, 9, 23))

    def test_a_meal_at_the_choices_time(self):
        group = self.choice("eat", meal_type="dinner", start_time=time(19, 30))
        keller = Option.objects.create(group=group, title="Augustiner", poi=self.keller, notes="Beer garden")
        response = self.pick(keller, fetch=True)
        meal = Meal.objects.get()
        self.assertEqual((meal.day, meal.name, meal.meal_type, meal.reserved_time, meal.poi, meal.why_recommended),
                         (self.day, "Augustiner", "dinner", time(19, 30), self.keller, "Beer garden"))
        self.assertEqual(response.json(), {"url": reverse("trips:meal_edit", args=[self.trip.pk, self.day.pk, meal.pk]),
                                           "anchor": f"meal-{meal.pk}"})

    def test_an_activity_with_its_times_and_place(self):
        group = self.choice("do", start_time=time(11), end_time=time(16))
        tent = Option.objects.create(group=group, title="Tour of the Wiesn", place_text="Hacker-Festzelt",
                                     est_cost=Decimal("20"), currency="EUR")
        self.pick(tent)
        activity = TripActivity.objects.get()
        self.assertEqual((activity.title, activity.kind, activity.place_text, activity.start_time, activity.end_time,
                          activity.est_cost, activity.option),
                         ("Tour of the Wiesn", "tour", "Hacker-Festzelt", time(11), time(16), Decimal("20"), tent))

    def test_a_planned_leg_with_cities_and_zones(self):
        group = self.choice("travel", mode="train")
        train = Option.objects.create(group=group, title="RE", from_text="Augsburg", to_text="Munich",
                                      est_cost=Decimal("12"), currency="EUR")
        self.pick(train)
        leg = TransportLeg.objects.get()
        self.assertEqual((leg.mode, leg.date, leg.origin_city, leg.destination_city, leg.origin_timezone, leg.cost,
                          leg.is_planned),
                         ("train", self.day.date, self.augsburg, self.munich, "Europe/Berlin", Decimal("12"), True))

    def test_anything_makes_nothing(self):
        group = self.choice("any")
        option = Option.objects.create(group=group, title="Castle")
        response = self.pick(option)
        self.assertFalse(Lodging.objects.exists() or Meal.objects.exists() or TripActivity.objects.exists())
        self.assertEqual(response["Location"], reverse("trips:trip_detail", args=[self.trip.pk]) + "#day-2")

    def test_an_option_with_its_own_item_makes_nothing(self):
        group = self.choice("stay", nights=2)
        option = Option.objects.create(group=group, title="Augusta")
        Lodging.objects.create(trip=self.trip, name="Hotel Augusta", check_in=self.day.date,
                               check_out=date(2027, 9, 21), option=option)
        self.pick(option)
        self.assertEqual(Lodging.objects.count(), 1)
        option.refresh_from_db()
        self.assertIsNone(option.made_id)


class CountingTests(Fixture):
    def test_the_item_counts_only_while_picked_and_picking_again_reuses_it(self):
        group = self.choice("stay", nights=2)
        rugs = Option.objects.create(group=group, title="Rugs Hotel", est_cost=95, currency="EUR")
        flat = Option.objects.create(group=group, title="Flat", est_cost=80, currency="EUR")
        self.pick(rugs)
        stay = Lodging.objects.get()
        self.assertEqual(list(Lodging.objects.filter(counts_q())), [stay])
        page = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        self.assertIn(f'id="stay-{stay.pk}"', page)
        self.assertIn("Sleeping: ", page)  # its later night
        group.refresh_from_db()
        group.reopen()
        self.assertFalse(Lodging.objects.filter(counts_q()).exists())  # kept, inside its option, not counting
        self.pick(flat)
        self.assertEqual(Lodging.objects.count(), 2)
        self.assertEqual(list(Lodging.objects.filter(counts_q()).values_list("name", flat=True)), ["Flat"])
        group.refresh_from_db()
        group.reopen()
        self.pick(rugs)
        self.assertEqual(Lodging.objects.count(), 2)  # the Rugs stay again, not a third
        self.assertEqual(list(Lodging.objects.filter(counts_q()).values_list("name", flat=True)), ["Rugs Hotel"])

    def test_a_deleted_item_is_made_again(self):
        group = self.choice("eat", meal_type="lunch")
        option = Option.objects.create(group=group, title="Café")
        self.pick(option)
        Meal.objects.get().delete()
        group.refresh_from_db()
        group.reopen()
        self.pick(option)
        self.assertEqual(Meal.objects.get().name, "Café")

    def test_split_makes_one_per_track(self):
        ada, bo = Traveler.objects.create(name="Ada"), Traveler.objects.create(name="Bo")
        self.trip.travelers.set([ada, bo])
        group = self.choice("do", start_time=time(14))
        castle = Option.objects.create(group=group, title="Castle")
        museum = Option.objects.create(group=group, title="Museum")
        Option.objects.create(group=group, title="Nobody")
        self.client.force_login(self.editor)
        self.client.post(reverse("trips:group_split", args=[self.trip.pk, group.pk]),
                         {f"t{ada.pk}": castle.pk, f"t{bo.pk}": museum.pk})
        self.assertEqual(sorted(TripActivity.objects.values_list("title", "option__title")),
                         [("Castle", "Castle"), ("Museum", "Museum")])
        self.assertEqual(TripActivity.objects.filter(counts_q()).count(), 2)

    def test_history_and_undo(self):
        group = self.choice("eat", meal_type="dinner")
        option = Option.objects.create(group=group, title="Keller")
        self.pick(option)
        summaries = list(TripChange.objects.order_by("pk").values_list("summary", flat=True))
        self.assertTrue(any(s.startswith("Added dinner at Keller") for s in summaries), summaries)
        pick = TripChange.objects.filter(item_type="optiongroup").latest("pk")
        self.assertEqual(pick.actor, self.editor)
        changes.undo(pick)
        group.refresh_from_db()
        self.assertEqual(group.state, "open")
        self.assertTrue(Meal.objects.filter(option=option).exists())  # kept, under the option (Considered)
        self.assertFalse(Meal.objects.filter(counts_q()).exists())


class PageTests(Fixture):
    def test_the_panel_opens_the_new_item(self):
        """The trip page, reached with ?item=, holds the new item's row, which panel.js opens."""
        group = self.choice("eat", meal_type="dinner", start_time=time(19))
        option = Option.objects.create(group=group, title="Keller")
        location = self.pick(option)["Location"]
        meal = Meal.objects.get()
        self.assertIn(f"?item=meal-{meal.pk}", location)
        page = self.client.get(location).content.decode()
        self.assertIn(f'id="meal-{meal.pk}" data-panel="', page)

    def test_make_item_is_the_one_place(self):
        group = self.choice("stay")
        option = Option.objects.create(group=group, title="Hut")
        stay = options.make_item(option)
        self.assertEqual((stay.check_out - stay.check_in).days, 1)  # no nights known: one night
        self.assertEqual(options.make_item(option), stay)
