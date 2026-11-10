"""Move the whole trip by N days (docs/plans/shift-and-reorder-days.md, DR1): ``apps/trips/reschedule.py`` and
``trips:trip_shift`` — days, journeys (wall-clock kept), stays and the trip's dates move; payments, ``booked_on``,
events and due dates don't; booking to-dos; warnings; one undoable history line; the fit-the-days page's offer."""

from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.activities.models import ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.catalogue_notes.models import CatalogueNote
from apps.events.models import Event
from apps.locations.models import POI, City, Country
from apps.trips import changes, reschedule
from apps.trips.models import (
    BookingTask,
    Confirmation,
    Day,
    Lodging,
    Meal,
    Section,
    TransportLeg,
    Traveler,
    Trip,
    TripActivity,
    TripChange,
    TripExpense,
    TripGrant,
    TripRole,
)

User = get_user_model()
UTC = dt_timezone.utc
APPROVED = ApprovalStatus.APPROVED


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.other = User.objects.create_user("bo", "bo@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(
            name="Bavaria",
            start_date=date(2027, 9, 17),
            end_date=date(2027, 9, 20),
            created_by=self.editor,
            home_currency="EUR",
        )
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.other, role=TripRole.VIEWER)
        self.days = [
            Day.objects.create(trip=self.trip, day_number=n, date=date(2027, 9, 16 + n), theme=f"T{n}")
            for n in (1, 2, 3, 4)
        ]
        # 10:15 CEST on Sep 19 = 08:15 UTC.
        self.train = TransportLeg.objects.create(
            trip=self.trip,
            mode="train",
            operator="DB",
            origin="Augsburg",
            destination="Munich",
            origin_timezone="Europe/Berlin",
            destination_timezone="Europe/Berlin",
            departure_at=datetime(2027, 9, 19, 8, 15, tzinfo=UTC),
            arrival_at=datetime(2027, 9, 19, 8, 55, tzinfo=UTC),
        )
        self.planned = TransportLeg.objects.create(
            trip=self.trip, mode="train", origin="Munich", destination="Füssen", date=date(2027, 9, 20)
        )
        self.hotel = Lodging.objects.create(
            trip=self.trip, name="Hotel Laimer Hof", check_in=date(2027, 9, 17), check_out=date(2027, 9, 20)
        )
        self.meal = Meal.objects.create(day=self.days[1], name="Augustiner")
        self.client.force_login(self.editor)

    def url(self, **query):
        from urllib.parse import urlencode

        return reverse("trips:trip_shift", args=[self.trip.pk]) + (f"?{urlencode(query)}" if query else "")


class MoveTests(Fixture):
    def test_everything_moves_backwards_and_forwards(self):
        for n in (-7, 3):
            self.trip.refresh_from_db()
            start = self.trip.start_date
            reschedule.shift(self.trip, n, self.editor)
            self.trip.refresh_from_db()
            self.assertEqual((self.trip.start_date - start).days, n)
        # Net: -4 days.
        self.trip.refresh_from_db()
        self.assertEqual((self.trip.start_date, self.trip.end_date), (date(2027, 9, 13), date(2027, 9, 16)))
        self.assertEqual(
            [d.date for d in Day.objects.filter(trip=self.trip).order_by("day_number")],
            [date(2027, 9, 13), date(2027, 9, 14), date(2027, 9, 15), date(2027, 9, 16)],
        )
        self.train.refresh_from_db()
        self.assertEqual((self.train.date, self.train.departure_local_str), (date(2027, 9, 15), "10:15 AM CEST"))
        self.planned.refresh_from_db()
        self.assertEqual((self.planned.date, self.planned.departure_at), (date(2027, 9, 16), None))
        self.hotel.refresh_from_db()
        self.assertEqual((self.hotel.check_in, self.hotel.check_out), (date(2027, 9, 13), date(2027, 9, 16)))
        self.meal.refresh_from_db()
        self.assertEqual(self.meal.day.date, date(2027, 9, 14))  # contents ride along with their day

    def test_wall_clock_kept_across_the_end_of_summer_time(self):
        # 10:15 CET on Nov 2 2027 (09:15 UTC) a week earlier is 10:15 CEST on Oct 26 (08:15 UTC).
        leg = TransportLeg.objects.create(
            trip=self.trip,
            mode="train",
            origin="A",
            destination="B",
            origin_timezone="Europe/Berlin",
            destination_timezone="Europe/Berlin",
            departure_at=datetime(2027, 11, 2, 9, 15, tzinfo=UTC),
            arrival_at=datetime(2027, 11, 2, 10, 15, tzinfo=UTC),
        )
        reschedule.shift(self.trip, -7, self.editor)
        leg.refresh_from_db()
        self.assertEqual(leg.departure_at, datetime(2027, 10, 26, 8, 15, tzinfo=UTC))
        self.assertEqual(
            (leg.date, leg.departure_local_str, leg.arrival_local_str),
            (date(2027, 10, 26), "10:15 AM CEST", "11:15 AM CEST"),
        )

    def test_payments_booked_on_events_and_due_dates_stay(self):
        ada = Traveler.objects.create(name="Ada")
        paid = TripExpense.objects.create(
            trip=self.trip,
            description="Deposit",
            amount=Decimal("10"),
            currency="EUR",
            paid_by=ada,
            spent_on=date(2027, 6, 1),
        )
        booking = Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS", booked_on=date(2027, 5, 1))
        booking.link(self.hotel)
        task = BookingTask.objects.create(trip=self.trip, title="Deposit due", due=date(2027, 8, 1))
        reschedule.shift(self.trip, -7, self.editor, booking_todos=False)
        paid.refresh_from_db(), booking.refresh_from_db(), task.refresh_from_db()
        self.assertEqual(
            (paid.spent_on, booking.booked_on, task.due), (date(2027, 6, 1), date(2027, 5, 1), date(2027, 8, 1))
        )
        reschedule.shift(self.trip, -1, self.editor, move_due=True, booking_todos=False)
        task.refresh_from_db()
        self.assertEqual(task.due, date(2027, 7, 31))

    def test_one_booking_todo_per_confirmation_covering_its_items(self):
        flight = Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS")
        flight.link(self.train)
        flight.link(self.planned)
        hotel = Confirmation.objects.create(trip=self.trip, confirmation_number="5305434791")
        hotel.link(self.hotel)
        Confirmation.objects.create(trip=self.trip, confirmation_number="INS-1", label="Insurance")  # covers nothing
        done = reschedule.shift(self.trip, -7, self.editor)
        tasks = {task.title: task for task in done["made"]}
        self.assertEqual(
            set(tasks), {"Change booking GCH7JS to the new dates", "Change booking 5305434791 to the new dates"}
        )
        self.assertEqual(set(tasks["Change booking GCH7JS to the new dates"].covered()), {self.train, self.planned})
        self.assertEqual(list(tasks["Change booking 5305434791 to the new dates"].covered()), [self.hotel])
        self.assertEqual(tasks["Change booking GCH7JS to the new dates"].priority, BookingTask.Priority.HIGH)

    def test_refuses_no_move(self):
        with self.assertRaises(reschedule.CannotMove):
            reschedule.shift(self.trip, 0, self.editor)


class HistoryTests(Fixture):
    def test_one_line_and_undo_restores_everything(self):
        Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS").link(self.train)
        task = BookingTask.objects.create(trip=self.trip, title="Seats", due=date(2027, 8, 1))
        before_count = TripChange.objects.filter(trip=self.trip).count()
        done = reschedule.shift(self.trip, -7, self.editor, move_due=True)
        self.assertEqual(TripChange.objects.filter(trip=self.trip).count(), before_count + 1)
        line = done["change"]
        self.assertTrue(line.summary.startswith("Moved the trip 7 days earlier: Sep 17–20 → Sep 10–13"))
        self.assertEqual((line.item_type, line.item_id, line.actor), ("trip", self.trip.pk, self.editor))
        self.assertTrue(changes.can_undo(line, changes.latest_change_ids(self.trip)))
        response = self.client.post(reverse("trips:change_undo", args=[self.trip.pk, line.pk]))
        self.assertEqual(response.status_code, 302)
        self.trip.refresh_from_db(), self.train.refresh_from_db(), self.hotel.refresh_from_db(), task.refresh_from_db()
        self.assertEqual((self.trip.start_date, self.trip.end_date), (date(2027, 9, 17), date(2027, 9, 20)))
        self.assertEqual(self.train.departure_at, datetime(2027, 9, 19, 8, 15, tzinfo=UTC))
        self.assertEqual((self.hotel.check_in, task.due), (date(2027, 9, 17), date(2027, 8, 1)))
        self.assertEqual(
            [d.date for d in Day.objects.filter(trip=self.trip).order_by("day_number")],
            [date(2027, 9, 17), date(2027, 9, 18), date(2027, 9, 19), date(2027, 9, 20)],
        )
        self.assertFalse(BookingTask.objects.filter(title__startswith="Change booking").exists())

    def test_undo_keeps_an_edited_todo_and_refuses_after_another_change(self):
        Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS").link(self.train)
        line = reschedule.shift(self.trip, -7, self.editor)["change"]
        made = BookingTask.objects.get(title__startswith="Change booking")
        made.notes = "Called Delta"
        made.save()
        kept = reschedule.undo_shift(line, self.editor)
        self.assertEqual(kept, [made])
        self.assertTrue(BookingTask.objects.filter(pk=made.pk).exists())
        # A second move, then an edit: its Undo isn't offered and is refused.
        line = reschedule.shift(self.trip, 2, self.editor)["change"]
        self.meal.name = "Hofbräuhaus"
        self.meal.save()
        self.assertFalse(changes.can_undo(line, changes.latest_change_ids(self.trip)))
        with self.assertRaises(reschedule.CannotMove):
            reschedule.undo_shift(line, self.editor)

    def test_no_time_change_notice_per_leg_one_notice_when_soon(self):
        with (
            mock.patch("apps.notifications.services.notify") as notify,
            mock.patch("django.utils.timezone.localdate", return_value=date(2027, 9, 5)),
            self.captureOnCommitCallbacks(execute=True),
        ):
            reschedule.shift(self.trip, 21, self.editor)  # Sep 19 → Oct 10: not soon
        notify.assert_not_called()
        with (
            mock.patch("apps.notifications.services.notify") as notify,
            mock.patch("django.utils.timezone.localdate", return_value=date(2027, 9, 5)),
            self.captureOnCommitCallbacks(execute=True),
        ):
            reschedule.shift(self.trip, -32, self.editor)  # the train now Sep 8: within a week
        self.assertEqual(notify.call_count, 1)  # one notice, to the other person, not one per leg
        self.assertEqual(notify.call_args.args[0], self.other)
        self.assertIn("has moved", notify.call_args.args[2])


class PageTests(Fixture):
    def test_preview_saves_nothing_and_lists_the_warnings(self):
        Confirmation.objects.create(trip=self.trip, confirmation_number="5305434791").link(self.hotel)
        de = Country.objects.create(
            name="Germany", slug="de", iso_code="DE", iso3_code="DEU", continent="Europe", approval_status=APPROVED
        )
        munich = City.objects.create(
            name="Munich", slug="munich", country=de, latitude=0, longitude=0, approval_status=APPROVED
        )
        category, _ = ActivityCategory.objects.get_or_create(name="Festival", defaults={"slug": "festival"})
        fest = Event.objects.create(
            name="Oktoberfest 2027",
            slug="oktoberfest-2027",
            description="d",
            category=category,
            start_date=date(2027, 9, 18),
            end_date=date(2027, 10, 3),
            city=munich,
            approval_status=APPROVED,
        )
        TripActivity.objects.create(trip=self.trip, day=self.days[1], title="Hacker-Festzelt", event=fest)
        Section.objects.create(day=self.days[0], section_type="note", title="Oktoberfest 2027", event=fest)
        diner = POI.objects.create(
            name="Moab Diner", slug="moab-diner", city=munich, latitude=0, longitude=0, approval_status=APPROVED
        )
        # Moved 8 days earlier, Day 3 (Sun Sep 19) becomes Sat Sep 11, and the diner shuts on Saturdays.
        CatalogueNote.objects.create(
            poi=diner,
            text="Closed Saturdays.",
            closed_weekdays=[5],
            checked_on=date(2026, 10, 1),
            approval_status=APPROVED,
        )
        Meal.objects.create(day=self.days[2], name="Moab Diner", poi=diner)
        TransportLeg.objects.create(
            trip=self.trip, mode="plane", origin="PIT", destination="FRA", date=date(2027, 9, 16)
        )
        BookingTask.objects.create(trip=self.trip, title="No due date")
        BookingTask.objects.create(trip=self.trip, title="Deposit", due=date(2027, 8, 1))
        response = self.client.get(self.url(start="2027-09-09", keep_booked=0))
        html = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Sep 17–20 → Sep 9–12", html)
        self.assertIn("5305434791</span> · Hotel Laimer Hof · booked for Sep 17–20, would be Sep 9–12", html)
        self.assertIn("Hacker-Festzelt is linked to Oktoberfest 2027, Sep 18–Oct 3; Day 2 will be Sep 10", html)
        self.assertIn("Oktoberfest 2027 runs Sep 18–Oct 3; Day 1 will be Sep 9", html)  # named like its event
        self.assertIn("Moab Diner is closed on Saturdays; Day 3 will be a Saturday", html)
        self.assertIn("PIT → FRA is on Sep 16, which isn't one of the trip's days", html)
        self.assertIn("Also move to-do due dates (1)", html)  # only the to-do with a due date
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.start_date, date(2027, 9, 17))  # nothing saved

    def test_apply_moves_and_says_so(self):
        Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS").link(self.train)
        response = self.client.post(
            self.url(), {"start": "2027-09-10", "booking_todos": "1", "keep_booked": "0"}, follow=True
        )
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.start_date, date(2027, 9, 10))
        self.assertContains(response, "Moved the trip to Sep 10–13. 1 booking to change: see To book.")
        self.assertEqual(BookingTask.objects.filter(title__startswith="Change booking").count(), 1)

    def test_editors_only(self):
        self.client.force_login(self.other)  # a viewer
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.assertEqual(self.client.post(self.url(), {"start": "2027-09-10"}).status_code, 403)
        self.client.force_login(User.objects.create_user("st", "st@example.com", "pw-1234-abcd"))
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_settings_links_it(self):
        html = self.client.get(reverse("trips:trip_settings", args=[self.trip.pk])).content.decode()
        self.assertIn(f'href="{self.url()}">Move the whole trip…</a>', html)


class FitDaysOfferTests(Fixture):
    def settings_post(self, start, end):
        data = {
            "name": "Bavaria",
            "start_date": start,
            "end_date": end,
            "status": "starting",
            "home_currency": "EUR",
            "home_currency_other": "",
            "food_allowance": "",
            "food_allowance_currency": "",
            "food_allowance_currency_other": "",
            "destination": "",
            "notes": "",
            "new_traveler_name": "",
        }
        return self.client.post(reverse("trips:trip_settings", args=[self.trip.pk]), data)

    def test_a_new_start_date_offers_to_move_everything(self):
        response = self.settings_post("2027-09-10", "2027-09-13")
        fit = reverse("trips:trip_days_fit", args=[self.trip.pk])
        self.assertRedirects(response, fit + "?moved_from=2027-09-17", fetch_redirect_response=False)
        html = self.client.get(response.url).content.decode()
        self.assertIn("Your days are still on Sep 17–20.", html)
        self.assertIn(f'href="{self.url(moved_from="2027-09-17")}">Move everything to start on Sep 10</a>', html)
        # The contents move by the difference; the trip's dates were already saved.
        preview = self.client.get(self.url(moved_from="2027-09-17")).content.decode()
        self.assertIn("7 days earlier", preview)
        self.client.post(self.url(), {"moved_from": "2027-09-17"})
        self.trip.refresh_from_db()
        self.assertEqual((self.trip.start_date, self.trip.end_date), (date(2027, 9, 10), date(2027, 9, 13)))
        self.assertEqual(
            sorted(d.date for d in Day.objects.filter(trip=self.trip)),
            [date(2027, 9, 10) + timedelta(days=n) for n in range(4)],
        )
        line = TripChange.objects.filter(trip=self.trip).latest("id")
        self.assertTrue(line.summary.startswith("Moved the days, journeys and stays 7 days earlier"))
        reschedule.undo_shift(line, self.editor)  # undoing it leaves the trip's own dates alone
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.start_date, date(2027, 9, 10))
        self.assertEqual(Day.objects.get(pk=self.days[0].pk).date, date(2027, 9, 17))

    def test_a_different_end_change_still_goes_to_fit_the_days(self):
        self.settings_post("2027-09-10", "2027-09-15")  # start -7, two more days at the end
        response = self.client.post(self.url(), {"moved_from": "2027-09-17"})
        self.assertRedirects(
            response, reverse("trips:trip_days_fit", args=[self.trip.pk]), fetch_redirect_response=False
        )

    def test_only_the_end_date_moved_no_offer(self):
        response = self.settings_post("2027-09-17", "2027-09-18")
        self.assertNotIn("moved_from", response.url)
