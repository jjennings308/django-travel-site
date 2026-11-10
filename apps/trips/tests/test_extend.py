"""Add days at the start or end (docs/plans/shift-and-reorder-days.md, DR4): ``reschedule.extend_plan`` / ``extend``
and ``trips:trip_extend`` — only the trip's dates grow and the new dates get empty days; every existing day, journey,
stay, booking and day's contents stays where it is. One undoable history line; Undo deletes the added days (refusing
when something has been put on them since)."""

from datetime import date, timedelta

from django.urls import reverse

from apps.trips import changes, reschedule
from apps.trips.models import BookingTask, Confirmation, Day, Meal, TransportLeg, TripChange
from apps.trips.tests.test_reschedule import Fixture

START = date(2027, 9, 15)


class ExtendPlanTests(Fixture):
    def test_start_adds_before_and_renumbers_the_existing_days(self):
        plan = reschedule.extend_plan(self.trip, 2, "start")
        self.assertEqual(plan["old_range"], (date(2027, 9, 17), date(2027, 9, 20)))
        self.assertEqual(plan["new_range"], (START, date(2027, 9, 20)))
        self.assertEqual(plan["new_dates"], [START, START + timedelta(days=1)])
        self.assertEqual([(row["old"], row["new"]) for row in plan["renumbered"]], [(1, 3), (2, 4), (3, 5), (4, 6)])
        self.assertEqual((plan["old_span"], plan["new_span"]), ("Sep 17–20", "Sep 15–20"))

    def test_end_adds_after_and_keeps_the_numbers(self):
        plan = reschedule.extend_plan(self.trip, 2, "end")
        self.assertEqual(plan["new_range"], (date(2027, 9, 17), date(2027, 9, 22)))
        self.assertEqual(plan["new_dates"], [date(2027, 9, 21), date(2027, 9, 22)])
        self.assertEqual(plan["renumbered"], [])

    def test_a_date_that_already_has_a_day_is_kept_not_made(self):
        Day.objects.create(trip=self.trip, day_number=0, date=START + timedelta(days=1))
        plan = reschedule.extend_plan(self.trip, 2, "start")
        self.assertEqual(plan["new_dates"], [START])
        self.assertEqual(plan["already"], [START + timedelta(days=1)])

    def test_refuses_bad_input(self):
        for n, at in ((0, "start"), (61, "start"), (1, "middle")):
            with self.assertRaises(reschedule.CannotMove):
                reschedule.extend_plan(self.trip, n, at)


class ExtendTests(Fixture):
    def booked(self):
        confirmation = Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS")
        confirmation.link(self.train)
        return confirmation

    def test_start_adds_days_and_leaves_everything_else_where_it_was(self):
        confirmation = self.booked()
        done = reschedule.extend(self.trip, 2, "start", self.editor)
        self.trip.refresh_from_db()
        self.assertEqual((self.trip.start_date, self.trip.end_date), (START, date(2027, 9, 20)))
        self.assertEqual(
            sorted(Day.objects.filter(trip=self.trip).values_list("date", flat=True)),
            [START + timedelta(days=n) for n in range(6)],
        )
        made = sorted(done["made_days"], key=lambda day: day.date)
        self.assertEqual([day.date for day in made], [START, START + timedelta(days=1)])
        self.assertFalse(Meal.objects.filter(day__in=made).exists())
        for day, number in zip(self.days, (3, 4, 5, 6)):
            day.refresh_from_db()
            self.assertEqual(day.day_number, number)
        self.assertEqual([day.date for day in self.days], [date(2027, 9, 16 + n) for n in range(1, 5)])
        self.meal.refresh_from_db()
        self.assertEqual(self.meal.day, self.days[1])
        self.train.refresh_from_db()
        self.assertEqual(self.train.date, date(2027, 9, 19))
        self.hotel.refresh_from_db()
        self.assertEqual((self.hotel.check_in, self.hotel.check_out), (date(2027, 9, 17), date(2027, 9, 20)))
        confirmation.refresh_from_db()
        self.assertIsNone(confirmation.booked_on)
        self.assertFalse(BookingTask.objects.filter(trip=self.trip).exists())
        line = TripChange.objects.filter(trip=self.trip).latest("id")
        self.assertEqual(line.summary, "Added 2 days at the start: Sep 15–16")
        self.assertTrue(changes.can_undo(line, changes.latest_change_ids(self.trip)))

    def test_end_adds_days_and_keeps_the_existing_numbers(self):
        reschedule.extend(self.trip, 2, "end", self.editor)
        self.trip.refresh_from_db()
        self.assertEqual((self.trip.start_date, self.trip.end_date), (date(2027, 9, 17), date(2027, 9, 22)))
        self.assertEqual([day.day_number for day in self.days], [1, 2, 3, 4])
        self.assertEqual(
            list(Day.objects.filter(trip=self.trip).order_by("day_number").values_list("date", flat=True)),
            [date(2027, 9, 16 + n) for n in range(1, 7)],
        )
        self.assertEqual(
            TripChange.objects.filter(trip=self.trip).latest("id").summary, "Added 2 days at the end: Sep 21–22"
        )

    def test_a_wanted_date_that_already_has_a_day_is_used_not_made_again(self):
        Day.objects.filter(pk=self.days[0].pk).update(date=START + timedelta(days=1))
        done = reschedule.extend(self.trip, 2, "start", self.editor)
        self.assertEqual([day.date for day in done["made_days"]], [START])
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.start_date, START)
        self.assertEqual(Day.objects.filter(trip=self.trip).count(), 5)
        self.assertEqual(
            TripChange.objects.filter(trip=self.trip).latest("id").summary, "Added 2 days at the start: Sep 15–16"
        )

    def test_undo_deletes_the_added_days_and_puts_the_dates_back(self):
        done = reschedule.extend(self.trip, 2, "start", self.editor)
        reschedule.undo_move(done["change"], self.editor)
        self.trip.refresh_from_db()
        self.assertEqual((self.trip.start_date, self.trip.end_date), (date(2027, 9, 17), date(2027, 9, 20)))
        self.assertFalse(Day.objects.filter(pk__in=[day.pk for day in done["made_days"]]).exists())
        self.assertEqual(
            list(Day.objects.filter(trip=self.trip).order_by("day_number").values_list("date", "day_number")),
            [(date(2027, 9, 16 + n), n) for n in range(1, 5)],
        )
        self.assertIn("Undid", TripChange.objects.filter(trip=self.trip).latest("id").summary)

    def test_undo_refuses_when_an_added_day_has_something_on_it(self):
        done = reschedule.extend(self.trip, 1, "end", self.editor)
        with changes.quiet():
            Meal.objects.create(day=done["made_days"][0], name="Dinner")
        with self.assertRaisesMessage(reschedule.CannotMove, "has things on it now"):
            reschedule.undo_move(done["change"], self.editor)

    def test_undo_refuses_when_a_journey_is_on_an_added_date(self):
        done = reschedule.extend(self.trip, 1, "end", self.editor)
        with changes.quiet():
            TransportLeg.objects.create(
                trip=self.trip,
                mode="train",
                origin="A",
                destination="B",
                date=done["made_days"][0].date,
            )
        with self.assertRaisesMessage(reschedule.CannotMove, "journey is on an added day now"):
            reschedule.undo_move(done["change"], self.editor)

    def test_undo_refuses_when_a_stay_starts_on_an_added_date(self):
        done = reschedule.extend(self.trip, 1, "end", self.editor)
        with changes.quiet():
            self.hotel.check_in = done["made_days"][0].date
            self.hotel.check_out = self.hotel.check_in + timedelta(days=1)
            self.hotel.save(update_fields=["check_in", "check_out"])
        with self.assertRaisesMessage(reschedule.CannotMove, "stay starts on an added day now"):
            reschedule.undo_move(done["change"], self.editor)


class ExtendViewTests(Fixture):
    def url(self, **query):
        from urllib.parse import urlencode

        return reverse("trips:trip_extend", args=[self.trip.pk]) + (f"?{urlencode(query)}" if query else "")

    def test_preview_then_add_from_the_page(self):
        html = self.client.get(self.url(n=2, at="start")).content.decode()
        self.assertIn("Sep 17–20 → Sep 15–20", html)
        self.assertIn("Day 1 (Sep 17) becomes Day 3", html)
        response = self.client.post(self.url(), {"n": "2", "at": "start"}, follow=True)
        self.assertIn(reverse("trips:trip_settings", args=[self.trip.pk]) + "#days", response.redirect_chain[-1][0])
        self.assertContains(response, "Added 2 days at the start: Sep 15–20. Everything else stayed where it was.")
        self.trip.refresh_from_db()
        self.assertEqual((self.trip.start_date, self.trip.end_date), (START, date(2027, 9, 20)))

    def test_end_preview_and_apply(self):
        html = self.client.get(self.url(n=1, at="end")).content.decode()
        self.assertIn("Sep 17–20 → Sep 17–21", html)
        self.assertNotIn("Day numbers change", html)
        self.client.post(self.url(), {"n": "1", "at": "end"})
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.end_date, date(2027, 9, 21))

    def test_a_bad_number_is_explained(self):
        html = self.client.get(self.url(n=0, at="start")).content.decode()
        self.assertIn("Add between 1 and 60 days.", html)
        response = self.client.post(self.url(), {"n": "many", "at": "start"}, follow=True)
        self.assertContains(response, "Type how many days to add.")

    def test_only_editors_can_open_it(self):
        self.client.force_login(self.other)  # viewer
        self.assertEqual(self.client.get(self.url(n=1)).status_code, 403)
        from django.contrib.auth import get_user_model

        stranger = get_user_model().objects.create_user("sara", "sara@example.com", "pw-1234-abcd")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.url(n=1)).status_code, 404)

    def test_undo_from_the_history_page(self):
        self.client.post(self.url(), {"n": "1", "at": "end"})
        line = TripChange.objects.filter(trip=self.trip).latest("id")
        response = self.client.post(reverse("trips:change_undo", args=[self.trip.pk, line.pk]), follow=True)
        self.assertContains(response, "Undone: the added days are gone and the trip is back on its old dates.")
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.end_date, date(2027, 9, 20))

    def test_settings_and_the_fit_page_link_to_it(self):
        target = reverse("trips:trip_extend", args=[self.trip.pk])
        self.assertContains(self.client.get(reverse("trips:trip_settings", args=[self.trip.pk])), target)
        self.assertContains(self.client.get(reverse("trips:trip_days_fit", args=[self.trip.pk])), target)
