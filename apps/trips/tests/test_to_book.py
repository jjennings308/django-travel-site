"""Reference's "To book" list you can work in (docs/plans/booking-todos.md, K2): one row per item still to book,
No plan yet or its to-dos, Other to-dos, Mark done in place, the quick actions and "No booking needed"."""
from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import prefetch_related_objects
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.trips import booking_tasks
from apps.trips.models import (BookingTask, Confirmation, Day, Lodging, TransportLeg, Trip, TripActivity, TripChange,
                               TripGrant, TripRole)
from apps.trips.tests.helpers import make_task

User = get_user_model()


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Bavaria", start_date=date(2027, 9, 20), end_date=date(2027, 9, 25),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.day1 = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 20))
        self.day3 = Day.objects.create(trip=self.trip, day_number=3, date=date(2027, 9, 22))
        self.out = self.leg("Augsburg Hbf", "München Hbf", date(2027, 9, 20))
        self.back = self.leg("München Hbf", "Augsburg Hbf", date(2027, 9, 22))
        self.walk_up = self.leg("Augsburg Hbf", "Ulm", date(2027, 9, 22), operator="")  # no operator: not bookable
        self.hotel = Lodging.objects.create(trip=self.trip, name="Hotel Laimer Hof", check_in=date(2027, 9, 20),
                                            check_out=date(2027, 9, 22))
        self.detail = reverse("trips:trip_detail", args=[self.trip.pk])

    def leg(self, origin, destination, when, operator="DB"):
        return TransportLeg.objects.create(trip=self.trip, mode="train", operator=operator, origin=origin,
                                           destination=destination, date=when)

    def to_book(self):
        from apps.trips.views import _attach_confirmations
        trip = Trip.objects.get(pk=self.trip.pk)
        prefetch_related_objects([trip], "transport", "lodging", "days", "booking_tasks__links")
        _attach_confirmations(trip)
        booking_tasks.attach(trip)
        return booking_tasks.to_book(trip)

    def page(self, user=None, name="trip_detail"):
        self.client.force_login(user or self.editor)
        return self.client.get(reverse(f"trips:{name}", args=[self.trip.pk])).content.decode()


class RowTests(Fixture):
    def test_no_plan_rows_in_date_order(self):
        rows = self.to_book()["rows"]
        self.assertEqual([(r["label"], r["no_plan"]) for r in rows],
                         [("Augsburg Hbf → München Hbf", True), ("Hotel Laimer Hof", True),
                          ("München Hbf → Augsburg Hbf", True)])
        self.assertEqual(rows[0]["day"], self.day1)

    def test_a_round_trip_todo_is_one_row_and_other_todos_follow(self):
        task = make_task(self.trip, "Book trains", self.out, self.back, priority=2)
        loose = BookingTask.objects.create(trip=self.trip, title="Travel insurance")
        found = self.to_book()
        rows = found["rows"]
        self.assertEqual([r["label"] for r in rows], ["Augsburg Hbf → München Hbf and back", "Hotel Laimer Hof"])
        self.assertEqual(([t.pk for t in rows[0]["tasks"]], rows[0]["no_plan"]), ([task.pk], False))
        self.assertEqual(found["other"], [loose])

    def test_an_unbookable_item_with_a_todo_shows(self):
        make_task(self.trip, "Check the Ulm train", self.walk_up)
        self.assertIn("Augsburg Hbf → Ulm", [r["label"] for r in self.to_book()["rows"]])

    def test_confirmed_and_no_booking_items_are_gone(self):
        Confirmation.attach_number(self.trip, "GCH7JS", self.out)
        self.hotel.no_booking = True
        self.hotel.save()
        self.assertEqual([r["label"] for r in self.to_book()["rows"]], ["München Hbf → Augsburg Hbf"])

    def test_an_open_todo_whose_items_are_all_confirmed_stays_under_other(self):
        task = make_task(self.trip, "Seat reservations", self.out)
        Confirmation.attach_number(self.trip, "GCH7JS", self.out)
        self.assertEqual(self.to_book()["other"], [task])


class PageTests(Fixture):
    def test_reference_rows_open_in_the_panel_with_quick_actions(self):
        task = make_task(self.trip, "Book trains", self.out, self.back)
        html = self.page()
        self.assertIn('id="to-book"', html)
        self.assertIn(f'id="to-book-leg-{self.out.pk}" data-to-book-row data-panel="'
                      f'{reverse("trips:task_edit", args=[self.trip.pk, task.pk])}"', html)
        self.assertIn(f'id="to-book-stay-{self.hotel.pk}" data-to-book-row data-panel="'
                      f'{reverse("trips:stay_edit", args=[self.trip.pk, self.hotel.pk])}"', html)
        self.assertIn(f'href="{reverse("trips:task_new", args=[self.trip.pk])}?stay={self.hotel.pk}" data-panel-link>Add a to-do',
                      html)
        self.assertIn(f'href="{reverse("trips:item_confirmations", args=[self.trip.pk, "stay", self.hotel.pk])}" '
                      f'data-panel-link>Add confirmation', html)
        self.assertIn(reverse("trips:item_no_booking", args=[self.trip.pk, "stay", self.hotel.pk]), html)
        self.assertIn("trips/to_book.js", html)
        self.assertIn('if (id === "still-to-book" || id === "not-booked") id = "to-book";', html)

    def test_readers_open_rows_read_only_and_get_no_actions(self):
        task = make_task(self.trip, "Book trains", self.out, self.back)
        html = self.page(self.viewer)
        self.assertIn(f'data-panel="{reverse("trips:item_panel", args=[self.trip.pk, "task", task.pk])}"', html)
        self.assertNotIn("data-to-book-actions", html)
        self.assertNotIn("data-mark-done", html)
        self.assertNotIn("trips/to_book.js", html)
        self.client.force_login(self.viewer)
        panel = self.client.get(reverse("trips:item_panel", args=[self.trip.pk, "task", task.pk])).content.decode()
        self.assertIn("data-panel-task", panel)
        self.assertIn("Augsburg Hbf → München Hbf and back", panel)

    def test_the_banner_counts_rows_and_other_todos(self):
        BookingTask.objects.create(trip=self.trip, title="Travel insurance")
        html = self.page()
        self.assertIn('href="#to-book" data-to-book-count>3 to book</a>', html)
        self.assertIn('href="#other-todos">1 other to-do</a>', html)

    def test_the_fragment_is_the_list_at_the_day_fragments_cost(self):
        make_task(self.trip, "Book trains", self.out, self.back)
        self.client.force_login(self.editor)
        with CaptureQueriesContext(connection) as day:
            self.client.get(reverse("trips:day_fragment", args=[self.trip.pk, self.day1.pk]))
        with CaptureQueriesContext(connection) as fragment:
            response = self.client.get(reverse("trips:to_book_fragment", args=[self.trip.pk]))
        self.assertEqual(len(fragment), len(day))  # the page's context, nothing more
        html = response.content.decode()
        self.assertTrue(html.strip().startswith('<div id="to-book"'))
        self.assertIn("Augsburg Hbf → München Hbf and back", html)
        self.client.force_login(User.objects.create_user("st", "st@example.com", "pw-1234-abcd"))
        self.assertEqual(self.client.get(reverse("trips:to_book_fragment", args=[self.trip.pk])).status_code, 404)


class MarkDoneTests(Fixture):
    def setUp(self):
        super().setUp()
        self.task = make_task(self.trip, "Book trains", self.out, self.back)
        self.url = reverse("trips:task_done", args=[self.trip.pk, self.task.pk])
        self.client.force_login(self.editor)

    def test_by_fetch_answers_204(self):
        response = self.client.post(self.url, {"next": self.detail + "#to-book"}, HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(response.status_code, 204)
        self.task.refresh_from_db()
        self.assertTrue(self.task.done)

    def test_by_form_goes_back(self):
        response = self.client.post(self.url, {"next": self.detail + "#to-book"})
        self.assertRedirects(response, self.detail + "#to-book", fetch_redirect_response=False)

    def test_viewers_cannot(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(self.url, HTTP_X_REQUESTED_WITH="fetch").status_code, 403)


class TodoPageTests(Fixture):
    def test_each_thing_once_todos_by_priority_then_no_plan(self):
        make_task(self.trip, "Book trains", self.out, self.back, priority=3)
        make_task(self.trip, "Pay deposit", priority=1)
        html = self.page(name="trip_todo")
        self.assertLess(html.index("Pay deposit"), html.index("Book trains"))  # priority order kept
        no_plan = html[html.index('id="no-plan"'):]
        self.assertIn("Hotel Laimer Hof", no_plan)
        self.assertNotIn("Augsburg Hbf → München Hbf", no_plan)  # it has a to-do, listed above
        self.assertIn("data-mark-done", html)
        self.assertIn(f'href="{reverse("trips:stay_edit", args=[self.trip.pk, self.hotel.pk])}?next=', no_plan)
        self.assertIn("trips/to_book.js", html)

    def test_bookings_lists_no_plan_rows_read_only(self):
        make_task(self.trip, "Book trains", self.out, self.back)
        html = self.page(self.viewer, name="trip_bookings")
        block = html[html.index('id="not-booked"'):]
        self.assertIn(f'href="{self.detail}?item=stay-{self.hotel.pk}#stay-{self.hotel.pk}">Hotel Laimer Hof</a>', block)
        self.assertNotIn("Augsburg Hbf → München Hbf and back", block)
        self.assertNotIn("data-to-book-actions", block)


class NoBookingTests(Fixture):
    def test_the_button_marks_it_and_undo_puts_it_back(self):
        self.client.force_login(self.editor)
        url = reverse("trips:item_no_booking", args=[self.trip.pk, "leg", self.out.pk])
        response = self.client.post(url, {"next": self.detail + "#to-book"})
        self.assertRedirects(response, self.detail + "#to-book", fetch_redirect_response=False)
        self.out.refresh_from_db()
        self.assertTrue(self.out.no_booking)
        html = self.page()
        self.assertNotIn(f'id="to-book-leg-{self.out.pk}"', html)
        self.assertIn("data-no-booking-needed>no booking needed</span>", html)
        self.assertTrue(TripChange.objects.filter(summary__icontains="booking").exists())  # in the history
        self.client.post(url, {"undo": "1"})
        self.out.refresh_from_db()
        self.assertFalse(self.out.no_booking)

    def test_editors_only_and_this_trip_only(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(reverse("trips:item_no_booking", args=[self.trip.pk, "leg", self.out.pk]))
                         .status_code, 403)
        other = Trip.objects.create(name="Other", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2),
                                    created_by=self.editor)
        theirs = TransportLeg.objects.create(trip=other, origin="X", destination="Y", date=date(2027, 1, 1))
        self.client.force_login(self.editor)
        self.assertEqual(self.client.post(reverse("trips:item_no_booking", args=[self.trip.pk, "leg", theirs.pk]))
                         .status_code, 404)
        self.assertEqual(self.client.post(reverse("trips:item_no_booking", args=[self.trip.pk, "meal", 1]))
                         .status_code, 404)

    def test_not_booked_skips_it_and_the_forms_save_it(self):
        self.hotel.no_booking = True
        self.hotel.save()
        trip = Trip.objects.get(pk=self.trip.pk)
        prefetch_related_objects([trip], "transport", "lodging", "days", "booking_tasks__links")
        booking_tasks.attach(trip)
        self.assertNotIn(self.hotel, [e["item"] for e in booking_tasks.not_booked(trip)])
        from apps.trips.forms import LegEditForm, LodgingForm, TripActivityForm
        self.assertIn("no_booking", LegEditForm(instance=self.out).fields)
        self.assertIn("no_booking", dict(LegEditForm(instance=self.out).GROUPS)["Details"])
        self.assertIn("no_booking", LodgingForm(instance=self.hotel).fields)
        activity = TripActivity.objects.create(trip=self.trip, day=self.day1, title="Tour", kind="tour")
        self.assertIn("no_booking", TripActivityForm(instance=activity, trip=self.trip).fields)
