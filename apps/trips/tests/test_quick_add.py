"""+ Add: one typed line becomes a rough item on its day (docs/plans/day-first-planning.md, P3)."""
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import City, Country
from apps.trips.models import Day, Lodging, Meal, Section, TransportLeg, Trip, TripActivity, TripGrant, TripRole
from apps.trips.quick_add import find_time, parse

User = get_user_model()


class ParseTests(SimpleTestCase):
    """The line → kind and fields table. Nothing is guessed that the line doesn't say."""

    TABLE = [
        ("Train Munich → Salzburg 9:15", {"kind": "travel", "mode": "train", "origin": "Munich",
                                          "destination": "Salzburg", "notes": "Around 09:15", "duration": None}),
        ("Train to Salzburg", {"kind": "travel", "mode": "train", "origin": "", "destination": "Salzburg"}),
        ("Fly PIT -> ATL ~2h", {"kind": "travel", "mode": "plane", "origin": "PIT", "destination": "ATL",
                                "duration": timedelta(hours=2)}),
        ("Drive Taos to Angel Fire ~45 min", {"kind": "travel", "mode": "pov", "origin": "Taos",
                                              "destination": "Angel Fire", "duration": timedelta(minutes=45)}),
        ("Hotel Laimer Hof 3 nights", {"kind": "stay", "name": "Hotel Laimer Hof", "nights": 3}),
        ("Stay at Gasthof Post", {"kind": "stay", "name": "Gasthof Post", "nights": 1}),
        ("Dinner Augustiner 7:30pm", {"kind": "eat", "name": "Augustiner", "meal_type": "dinner",
                                      "time": time(19, 30)}),
        ("Lunch at Café Tomaselli", {"kind": "eat", "name": "Café Tomaselli", "meal_type": "lunch", "time": None}),
        ("Coffee at Demel", {"kind": "eat", "name": "Demel", "meal_type": "snack"}),
        ("Tour of the salt mine 10am", {"kind": "do", "title": "Tour of the salt mine", "activity_kind": "tour",
                                        "time": time(10, 0)}),
        ("Tickets Neuschwanstein 14:30", {"kind": "do", "title": "Tickets Neuschwanstein", "activity_kind": "ticket",
                                          "time": time(14, 30)}),
        ("Museum Island", {"kind": "do", "activity_kind": "entry", "time": None}),
        ("Meet Debbie at 3pm", {"kind": "do", "title": "Meet Debbie", "activity_kind": "other", "time": time(15, 0)}),
        ("Remember the adapters", {"kind": "note", "text": "Remember the adapters"}),
        ("Beer garden", {"kind": "note"}),
        ("Day 4 is free", {"kind": "note"}),
    ]

    def test_the_table(self):
        for line, expected in self.TABLE:
            with self.subTest(line=line):
                found = parse(line)
                self.assertEqual({key: found.get(key) for key in expected}, expected)

    def test_a_kind_button_forces_the_kind(self):
        self.assertEqual(parse("Augustiner", kind="eat")["kind"], "eat")
        self.assertEqual(parse("Augustiner 12:30", kind="eat")["meal_type"], "lunch")  # the time decides
        self.assertEqual(parse("Laimer Hof", kind="stay"), {"kind": "stay", "name": "Laimer Hof", "nights": 1})
        self.assertEqual(parse("Munich", kind="travel")["origin"], "Munich")
        self.assertEqual(parse("Dinner Augustiner", kind="note"), {"kind": "note", "text": "Dinner Augustiner"})
        self.assertEqual(parse("", kind="stay")["name"], "A stay")

    def test_times(self):
        for text, expected in (("7pm", time(19)), ("7:30 pm", time(19, 30)), ("7.30am", time(7, 30)),
                               ("12am", time(0)), ("12pm", time(12)), ("19:30", time(19, 30)), ("9h15", time(9, 15)),
                               ("at 8:05", time(8, 5)), ("3 nights", None), ("Day 4", None), ("25:00", None),
                               ("13pm", None)):
            with self.subTest(text=text):
                self.assertEqual(find_time(text)[0], expected)


class AddTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Alps", start_date=date(2027, 9, 18), end_date=date(2027, 9, 21),
                                        created_by=self.editor, home_currency="USD")
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        at = Country.objects.create(name="Austria", slug="at", iso_code="AT", iso3_code="AUT", continent="Europe",
                                    currency_code="EUR", approval_status=ApprovalStatus.APPROVED)
        de = Country.objects.create(name="Germany", slug="de", iso_code="DE", iso3_code="DEU", continent="Europe",
                                    currency_code="EUR", approval_status=ApprovalStatus.APPROVED)
        self.munich = City.objects.create(name="Munich", slug="munich", country=de, latitude=0, longitude=0,
                                          timezone="Europe/Berlin", approval_status=ApprovalStatus.APPROVED)
        self.salzburg = City.objects.create(name="Salzburg", slug="salzburg", country=at, latitude=0, longitude=0,
                                            timezone="Europe/Vienna", approval_status=ApprovalStatus.APPROVED)
        self.day = Day.objects.create(trip=self.trip, day_number=2, date=date(2027, 9, 19), city=self.munich)
        self.other = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 18))
        self.url = reverse("trips:quick_add", args=[self.trip.pk, self.day.pk])
        self.client.force_login(self.editor)

    def add(self, text, kind="", fetch=True):
        extra = {"HTTP_X_REQUESTED_WITH": "fetch"} if fetch else {}
        return self.client.post(self.url, {"text": text, **({"kind": kind} if kind else {})}, **extra)

    def test_each_kind_lands_on_this_day_and_opens_its_page(self):
        leg = self.add("Train Munich → Salzburg 9:15").json()
        made = TransportLeg.objects.get()
        self.assertEqual(leg, {"url": reverse("trips:leg_edit", args=[self.trip.pk, made.pk]), "anchor": f"leg-{made.pk}"})
        self.assertEqual((made.date, made.mode, made.origin_city, made.destination_city, made.destination_timezone,
                          made.is_planned, made.notes, made.currency),
                         (self.day.date, "train", self.munich, self.salzburg, "Europe/Vienna", True, "Around 09:15", "EUR"))
        self.assertEqual(set(self.trip.cities.all()), {self.munich, self.salzburg})

        self.assertEqual(self.add("Hotel Laimer Hof 3 nights").json()["anchor"], f"stay-{Lodging.objects.get().pk}")
        stay = Lodging.objects.get()
        self.assertEqual((stay.check_in, stay.check_out, stay.city), (self.day.date, date(2027, 9, 22), self.munich))

        self.add("Dinner Augustiner 7:30pm")
        meal = Meal.objects.get()
        self.assertEqual((meal.day, meal.name, meal.meal_type, meal.reserved_time),
                         (self.day, "Augustiner", "dinner", time(19, 30)))

        self.add("Tour of the salt mine 10am")
        activity = TripActivity.objects.get()
        self.assertEqual((activity.day, activity.kind, activity.start_time), (self.day, "tour", time(10)))

        self.add("Bring euros for the tents")
        note = Section.objects.get()
        self.assertEqual((note.day, note.section_type, note.content),
                         (self.day, "note", {"tone": "", "paragraphs": ["Bring euros for the tents"]}))

    def test_train_to_a_place_leaves_from_the_days_city(self):
        self.add("Train to Salzburg")
        self.assertEqual(TransportLeg.objects.get().origin_city, self.munich)

    def test_a_kind_button_and_an_empty_line(self):
        self.add("", kind="stay")
        self.assertEqual(Lodging.objects.get().name, "A stay")
        response = self.add("")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Type what to add", response.json()["error"])

    def test_without_javascript_it_goes_to_the_items_page_and_back_to_the_day(self):
        response = self.add("Dinner Augustiner", fetch=False)
        meal = Meal.objects.get()
        self.assertRedirects(response, reverse("trips:meal_edit", args=[self.trip.pk, self.day.pk, meal.pk])
                             + "?next=/trips/%d/%%23day-2" % self.trip.pk, fetch_redirect_response=False)

    def test_editors_only(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.add("Dinner").status_code, 403)
        self.assertFalse(Meal.objects.exists())

    def test_the_trip_page_has_it_for_editors(self):
        page = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        self.assertIn(f'action="{self.url}"', page)
        for label in ("Travel", "Stay", "Do", "Eat", "Note"):
            self.assertIn(f'value="{label.lower()}" class="chip', page)
        self.client.force_login(self.viewer)
        self.assertNotIn("data-quick-add", self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode())
