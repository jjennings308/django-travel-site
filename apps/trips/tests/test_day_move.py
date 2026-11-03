"""Fixes to moving days after first use (docs/plans/shift-and-reorder-days.md, DR3): a day's new date moves its
journeys and one-night stays (``reschedule.move_day``) and is refused for another day's date or one outside the trip;
the day form has no day number; a reorder offers to move the stays it leaves behind; the fit page's start-date offer
(also when only the start moved, keeping the length); "Change booking" to-dos that know when they aren't needed; and
"To do:" on booked items."""
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.locations.models import City, Country
from apps.trips import reschedule
from apps.trips.models import (BookingTask, Confirmation, Day, Lodging, TransportLeg, Trip, TripChange, TripGrant,
                               TripRole)
from apps.trips.tests import test_reorder, test_reschedule

User = get_user_model()
UTC = dt_timezone.utc


class Fixture(TestCase):
    """Sep 10–16 with five days on Sep 10–14 (Sep 15 and 16 free); a 10:15 train and a one-night stay on Day 2;
    three nights on Days 3–5."""

    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Bavaria", start_date=date(2027, 9, 10), end_date=date(2027, 9, 16),
                                        created_by=self.editor, home_currency="EUR")
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        self.d = {n: Day.objects.create(trip=self.trip, day_number=n, date=date(2027, 9, 9 + n), theme=f"Theme {n}")
                  for n in range(1, 6)}
        self.train = TransportLeg.objects.create(  # 10:15 CEST on Sep 11
            trip=self.trip, mode="train", origin="Augsburg", destination="Munich", origin_timezone="Europe/Berlin",
            destination_timezone="Europe/Berlin", departure_at=datetime(2027, 9, 11, 8, 15, tzinfo=UTC),
            arrival_at=datetime(2027, 9, 11, 8, 55, tzinfo=UTC))
        self.inn = Lodging.objects.create(trip=self.trip, name="Gasthof Post", check_in=date(2027, 9, 11),
                                          check_out=date(2027, 9, 12))
        self.hotel = Lodging.objects.create(trip=self.trip, name="Hotel Laimer Hof", check_in=date(2027, 9, 12),
                                            check_out=date(2027, 9, 15))
        self.client.force_login(self.editor)

    def edit(self, day, **data):
        url = reverse("trips:day_edit", args=[self.trip.pk, day.pk])
        formset = self.client.get(url).context["meal_formset"]
        payload = {"date": day.date.isoformat(), "theme": day.theme, "meals_included": "",
                   f"{formset.prefix}-TOTAL_FORMS": "0", f"{formset.prefix}-INITIAL_FORMS": "0",
                   f"{formset.prefix}-MIN_NUM_FORMS": "0", f"{formset.prefix}-MAX_NUM_FORMS": "1000", **data}
        return self.client.post(url, payload, follow=True)


class MoveDayTests(Fixture):
    def test_a_new_date_moves_the_journeys_and_the_one_night_stay_and_renumbers(self):
        response = self.edit(self.d[2], date="2027-09-16", theme="Day trip")
        two = Day.objects.get(pk=self.d[2].pk)
        self.assertEqual((two.date, two.day_number, two.theme), (date(2027, 9, 16), 5, "Day trip"))
        self.assertEqual([Day.objects.get(pk=self.d[n].pk).day_number for n in (1, 3, 4, 5)], [1, 2, 3, 4])
        self.train.refresh_from_db()
        self.assertEqual((self.train.date, self.train.departure_local_str), (date(2027, 9, 16), "10:15 AM CEST"))
        self.inn.refresh_from_db()
        self.assertEqual((self.inn.check_in, self.inn.check_out), (date(2027, 9, 16), date(2027, 9, 17)))
        self.hotel.refresh_from_db()
        self.assertEqual(self.hotel.check_in, date(2027, 9, 12))
        text = [str(m) for m in response.context["messages"]]
        self.assertIn("Saved day 5. Moved it to Sep 16 with 1 journey and 1 stay.", text)
        # One history line for the move; Undo puts everything back.
        line = TripChange.objects.filter(trip=self.trip).latest("id")
        self.assertTrue(line.summary.startswith("Moved Day 2 Day trip from Sep 11 to Sep 16"), line.summary)
        self.client.post(reverse("trips:change_undo", args=[self.trip.pk, line.pk]))
        self.assertEqual([(d.date, d.day_number) for d in Day.objects.filter(trip=self.trip).order_by("day_number")],
                         [(date(2027, 9, 9 + n), n) for n in range(1, 6)])
        self.train.refresh_from_db()
        self.inn.refresh_from_db()
        self.assertEqual((self.train.date, self.inn.check_in), (date(2027, 9, 11), date(2027, 9, 11)))

    def test_a_longer_stay_touching_the_day_is_listed_not_moved(self):
        response = self.edit(self.d[4], date="2027-09-16")
        self.hotel.refresh_from_db()
        self.assertEqual((self.hotel.check_in, self.hotel.check_out), (date(2027, 9, 12), date(2027, 9, 15)))
        self.assertIn("Hotel Laimer Hof (Sep 12–15) wasn't moved: check it.",
                      [str(m) for m in response.context["messages"]])

    def test_a_booked_journey_gets_a_change_booking_todo(self):
        Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS").link(self.train)
        response = self.edit(self.d[2], date="2027-09-16")
        task = BookingTask.objects.get(trip=self.trip)
        self.assertEqual(task.title, "Change booking GCH7JS to the new dates")
        self.assertIn("1 booking to change: see To book.", str(list(response.context["messages"])[0]))

    def test_another_day_s_date_is_refused_with_a_link_to_reorder(self):
        response = self.edit(self.d[2], date="2027-09-12")
        self.assertEqual(response.context["form"].errors["date"],
                         ["Sep 12 is Day 3 — Theme 3. To swap days, use Reorder days."])
        self.assertContains(response, f'{reverse("trips:trip_reorder", args=[self.trip.pk])}?day={self.d[2].pk}')
        self.assertEqual(Day.objects.get(pk=self.d[2].pk).date, date(2027, 9, 11))

    def test_a_date_outside_the_trip_is_refused(self):
        response = self.edit(self.d[2], date="2027-09-20")
        self.assertIn("outside the trip (Sep 10–16)", response.context["form"].errors["date"][0])
        self.assertContains(response, "data-date-outside")
        self.train.refresh_from_db()
        self.assertEqual(self.train.date, date(2027, 9, 11))

    def test_keeping_the_date_moves_nothing(self):
        self.edit(self.d[2], theme="Renamed")
        self.assertEqual(Day.objects.get(pk=self.d[2].pk).theme, "Renamed")
        self.assertFalse(TripChange.objects.filter(trip=self.trip, summary__startswith="Moved").exists())

    def test_no_day_number_on_the_form_and_settings_still_renders(self):
        page = self.client.get(reverse("trips:day_edit", args=[self.trip.pk, self.d[2].pk]))
        self.assertNotIn("day_number", page.context["form"].fields)
        self.assertEqual(self.client.get(reverse("trips:trip_settings", args=[self.trip.pk])).status_code, 200)


class StaySuggestionTests(test_reorder.Fixture):
    """test_reorder's trip: Sep 10–14, Days 1–5, Hotel Laimer Hof on Days 2–4 (Sep 11–14)."""

    def kept(self, *order):
        return reschedule.reorder_plan(self.trip, self.pks(*order))["kept_stays"]

    def test_nights_still_next_to_each_other(self):
        [row] = self.kept(2, 4, 3, 1, 5)
        self.assertEqual(row["suggestion"]["new"], (date(2027, 9, 10), date(2027, 9, 13)))
        self.assertEqual(row["suggestion"]["text"], "Move Hotel Laimer Hof to Sep 10–13 (with its nights' days)")

    def test_by_the_city_of_most_of_its_nights(self):
        de = Country.objects.create(name="Germany", slug="de", iso_code="DE", iso3_code="DEU", continent="Europe")
        munich = City.objects.create(name="Munich", slug="munich", country=de, latitude=48.14, longitude=11.58)
        Day.objects.filter(pk__in=self.pks(2, 3)).update(city=munich)
        [row] = self.kept(4, 1, 2, 3, 5)
        self.assertEqual(row["suggestion"]["text"], "Move Hotel Laimer Hof to Sep 12–14 (with Munich's days)")

    def test_no_suggestion(self):
        [row] = self.kept(2, 1, 3, 5, 4)
        self.assertIsNone(row["suggestion"])

    def test_applied_when_ticked_skipped_when_not_and_undone(self):
        Confirmation.objects.create(trip=self.trip, confirmation_number="STAY1").link(self.hotel)
        reschedule.reorder(self.trip, self.pks(2, 4, 3, 1, 5), self.editor)
        self.hotel.refresh_from_db()
        self.assertEqual(self.hotel.check_in, date(2027, 9, 11))  # not ticked: stays
        self.assertFalse(BookingTask.objects.filter(title__contains="STAY1").exists())
        reschedule.undo_move(TripChange.objects.filter(trip=self.trip).latest("id"), self.editor)
        done = reschedule.reorder(self.trip, self.pks(2, 4, 3, 1, 5), self.editor, move_stays=[self.hotel.pk])
        self.hotel.refresh_from_db()
        self.assertEqual((self.hotel.check_in, self.hotel.check_out), (date(2027, 9, 10), date(2027, 9, 13)))
        self.assertEqual([task.title for task in done["made"]], ["Change booking STAY1 to the new dates"])
        reschedule.undo_move(TripChange.objects.filter(trip=self.trip).latest("id"), self.editor)
        self.hotel.refresh_from_db()
        self.assertEqual((self.hotel.check_in, self.hotel.check_out), (date(2027, 9, 11), date(2027, 9, 14)))
        self.assertFalse(BookingTask.objects.filter(trip=self.trip).exists())

    def test_the_page_ticks_the_offer_and_apply_sends_it(self):
        url = reverse("trips:trip_reorder", args=[self.trip.pk])
        order = {"order": self.pks(2, 4, 3, 1, 5)}
        html = self.client.post(url, {**order, "action": "preview"}).content.decode()
        self.assertIn(f'name="move_stays" value="{self.hotel.pk}" checked', html)
        self.client.post(url, {**order, "action": "apply", "move_stays": [self.hotel.pk]})
        self.hotel.refresh_from_db()
        self.assertEqual(self.hotel.check_in, date(2027, 9, 10))


class StartDateOfferTests(test_reschedule.Fixture):
    """test_reschedule's trip: Sep 17–20, four days."""

    settings_post = test_reschedule.FitDaysOfferTests.settings_post

    def test_an_earlier_start_alone_offers_keep_the_length_or_keep_the_end(self):
        response = self.settings_post("2027-09-10", "2027-09-20")  # James's case: no day falls outside
        fit = reverse("trips:trip_days_fit", args=[self.trip.pk])
        self.assertRedirects(response, fit + "?moved_from=2027-09-17&start_only=1", fetch_redirect_response=False)
        html = self.client.get(response.url).content.decode()
        self.assertIn("You moved the start to Sep 10.", html)
        self.assertIn("(keeps 4 days, ends Sep 13) or keep the end at Sep 20 (adds 7 empty days, below)?", html)
        shift = self.url(moved_from="2027-09-17") + "&amp;keep_length=1"
        self.assertIn(f'href="{shift}">Move the whole trip</a>', html)
        preview = self.client.get(self.url(moved_from="2027-09-17", keep_length=1)).content.decode()
        self.assertIn("and the trip's end to Monday, September 13 so it keeps its length", preview)
        response = self.client.post(self.url(), {"moved_from": "2027-09-17", "keep_length": "1"})
        self.assertRedirects(response, reverse("trips:trip_detail", args=[self.trip.pk]),
                             fetch_redirect_response=False)
        self.trip.refresh_from_db()
        self.assertEqual((self.trip.start_date, self.trip.end_date), (date(2027, 9, 10), date(2027, 9, 13)))
        self.assertEqual(sorted(d.date for d in Day.objects.filter(trip=self.trip)),
                         [date(2027, 9, 10) + timedelta(days=n) for n in range(4)])
        reschedule.undo_move(TripChange.objects.filter(trip=self.trip).latest("id"), self.editor)
        self.trip.refresh_from_db()  # back to just after Settings: the new start, the old end
        self.assertEqual((self.trip.start_date, self.trip.end_date), (date(2027, 9, 10), date(2027, 9, 20)))
        self.assertEqual(Day.objects.get(pk=self.days[0].pk).date, date(2027, 9, 17))

    def test_start_and_end_both_moved_with_every_day_inside_still_offers(self):
        response = self.settings_post("2027-09-10", "2027-09-25")
        self.assertNotIn("start_only", response.url)
        html = self.client.get(response.url).content.decode()
        self.assertIn("Your days are still on Sep 17–20.", html)

    def test_no_offer_when_the_days_already_start_on_the_new_start(self):
        Day.objects.filter(pk=self.days[0].pk).update(date=date(2027, 9, 10))
        html = self.client.get(reverse("trips:trip_days_fit", args=[self.trip.pk])
                               + "?moved_from=2027-09-17").content.decode()
        self.assertNotIn("data-shift-offer", html)


class BookedForTests(Fixture):
    def setUp(self):
        super().setUp()
        Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS").link(self.train)
        Confirmation.objects.create(trip=self.trip, confirmation_number="INN1").link(self.inn)
        self.edit(self.d[2], date="2027-09-16")
        self.tasks = {t.title.split()[2]: t for t in BookingTask.objects.filter(trip=self.trip)}

    def test_the_booked_dates_are_stored_and_hidden(self):
        task = self.tasks["GCH7JS"]
        self.assertEqual(task.booked_for(), {f"leg-{self.train.pk}": "2027-09-11"})
        self.assertNotIn("Booked for", task.visible_notes)
        self.assertEqual(self.tasks["INN1"].booked_for(), {f"stay-{self.inn.pk}": "2027-09-11/2027-09-12"})

    def test_back_on_its_booked_dates_offers_close(self):
        todo = reverse("trips:trip_todo", args=[self.trip.pk])
        self.assertNotContains(self.client.get(todo), "data-back-on-booked")
        # Moved back by hand (a later change, so not by Undo): the to-dos aren't needed now.
        Day.objects.filter(pk=self.d[2].pk).update(date=date(2027, 9, 11))
        TransportLeg.objects.filter(pk=self.train.pk).update(
            date=date(2027, 9, 11), departure_at=datetime(2027, 9, 11, 8, 15, tzinfo=UTC),
            arrival_at=datetime(2027, 9, 11, 8, 55, tzinfo=UTC))
        page = self.client.get(todo).content.decode()
        self.assertEqual(page.count("data-back-on-booked"), 1)  # the train's; the inn is still on Sep 16
        self.assertIn("Close this to-do", page)
        trip_page = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        self.assertIn("Back on its booked dates", trip_page)
        task = self.tasks["GCH7JS"]
        self.client.post(reverse("trips:task_done", args=[self.trip.pk, task.pk]), {"done": "1"})
        task.refresh_from_db()
        self.assertTrue(task.done)


class WordingTests(Fixture):
    def test_to_do_on_booked_items_still_to_book_on_others(self):
        Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS").link(self.train)
        for item in (self.train, self.inn):
            BookingTask.objects.create(trip=self.trip, title=f"Seats for {item.pk}").link(item)
        html = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        self.assertIn(f"To do: Seats for {self.train.pk}", html)
        self.assertIn(f"Still to book: Seats for {self.inn.pk}", html)
