"""The trip's To do page and to-dos added from their item (docs/plans/edit-by-day.md, E2)."""
import re
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.trips.tests.helpers import make_task
from apps.trips.models import (BookingTask, Day, Lodging, TransportLeg, Trip, TripActivity, TripGrant,
                               TripRole)

User = get_user_model()


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.stranger = User.objects.create_user("st", "st@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 20), end_date=date(2027, 9, 24),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.day4 = Day.objects.create(trip=self.trip, day_number=4, date=date(2027, 9, 23))
        self.leg = TransportLeg.objects.create(trip=self.trip, mode="train", origin="Munich", destination="Salzburg",
                                               date=self.day4.date)
        self.url = reverse("trips:trip_todo", args=[self.trip.pk])

    def get(self, user, url=None):
        self.client.force_login(user)
        return self.client.get(url or self.url)


class TodoPageTests(Fixture):
    def test_open_by_priority_then_due_date_and_done_folded_away(self):
        low = BookingTask.objects.create(trip=self.trip, title="Low one", priority=4)
        later = BookingTask.objects.create(trip=self.trip, title="High later", priority=2, due=date(2027, 8, 1))
        sooner = BookingTask.objects.create(trip=self.trip, title="High sooner", priority=2, due=date(2027, 7, 1))
        undated = BookingTask.objects.create(trip=self.trip, title="High undated", priority=2)
        done = BookingTask.objects.create(trip=self.trip, title="All done", priority=1, done=True)
        page = self.get(self.viewer)
        self.assertEqual(page.context["open_tasks"], [sooner, later, undated, low])
        self.assertEqual(page.context["done_tasks"], [done])
        html = page.content.decode()
        self.assertLess(html.index("data-done-tasks"), html.index("All done"))  # inside the Done fold

    def test_each_shows_its_item(self):
        make_task(self.trip, "Seats", self.leg)
        html = self.get(self.viewer).content.decode()
        detail = reverse("trips:trip_detail", args=[self.trip.pk])
        self.assertIn(f'href="{detail}?item=leg-{self.leg.pk}#leg-{self.leg.pk}">Day 4 · Munich → Salzburg</a>', html)
        self.assertIn("Seats", html)

    def test_viewers_read_editors_change_strangers_404(self):
        task = BookingTask.objects.create(trip=self.trip, title="Seats")
        html = self.get(self.viewer).content.decode()
        self.assertIn("Seats", html)
        for marker in ("data-task-new", "data-task-done", reverse("trips:task_edit", args=[self.trip.pk, task.pk])):
            self.assertNotIn(marker, html)
        html = self.get(self.editor).content.decode()
        self.assertIn("data-task-new", html)
        self.assertIn(reverse("trips:task_edit", args=[self.trip.pk, task.pk]), html)
        self.assertEqual(self.get(self.stranger).status_code, 404)
        self.client.force_login(self.viewer)
        for url in (reverse("trips:task_new", args=[self.trip.pk]),
                    reverse("trips:task_edit", args=[self.trip.pk, task.pk]),
                    reverse("trips:task_delete", args=[self.trip.pk, task.pk])):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.post(reverse("trips:task_done", args=[self.trip.pk, task.pk])).status_code, 403)


class TaskEditTests(Fixture):
    def data(self, **over):
        values = {"title": "Rail passes", "priority": "2", "due": "", "due_note": "", "day": "",
                  "confirmation": "", "order": "", "notes": ""}
        values.update(over)
        return values

    def test_add_from_a_leg_pre_picks_it_and_goes_back(self):
        new = reverse("trips:task_new", args=[self.trip.pk])
        self.client.force_login(self.editor)
        form = self.client.get(f"{new}?leg={self.leg.pk}").context["form"]
        self.assertEqual(form.initial["covers"], [f"leg-{self.leg.pk}"])
        leg_page = reverse("trips:leg_edit", args=[self.trip.pk, self.leg.pk])
        response = self.client.post(new, {**self.data(covers=[f"leg-{self.leg.pk}"]), "next": leg_page})
        self.assertEqual(response["Location"], leg_page)
        self.assertEqual(BookingTask.objects.get().covered(), [self.leg])

    def test_another_trips_item_is_not_a_choice(self):
        other = Trip.objects.create(name="Other", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        theirs = TransportLeg.objects.create(trip=other, mode="train", origin="A", destination="B",
                                             date=date(2027, 1, 1))
        their_day = Day.objects.create(trip=other, day_number=1, date=date(2027, 1, 1))
        self.client.force_login(self.editor)
        response = self.client.post(reverse("trips:task_new", args=[self.trip.pk]),
                                    self.data(covers=[f"leg-{theirs.pk}"], day=their_day.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.context["form"].errors), {"covers", "day"})
        self.assertFalse(BookingTask.objects.exists())
        theirs_task = BookingTask.objects.create(trip=other, title="x")
        self.assertEqual(self.client.get(reverse("trips:task_edit", args=[self.trip.pk, theirs_task.pk])).status_code,
                         404)

    def test_edit_mark_done_and_back_and_delete(self):
        task = BookingTask.objects.create(trip=self.trip, title="Seats")
        self.client.force_login(self.editor)
        response = self.client.post(reverse("trips:task_edit", args=[self.trip.pk, task.pk]), self.data(title="Seat 12A"))
        self.assertEqual(response["Location"], self.url)  # back to the To do page by default
        task.refresh_from_db()
        self.assertEqual(task.title, "Seat 12A")
        done = reverse("trips:task_done", args=[self.trip.pk, task.pk])
        self.client.post(done)
        task.refresh_from_db()
        self.assertTrue(task.done)
        self.client.post(done, {"done": "0"})
        task.refresh_from_db()
        self.assertFalse(task.done)
        response = self.client.post(reverse("trips:task_done", args=[self.trip.pk, task.pk]),
                                    {"next": "https://evil.example/"})
        self.assertEqual(response["Location"], self.url)
        self.client.post(reverse("trips:task_delete", args=[self.trip.pk, task.pk]))
        self.assertFalse(BookingTask.objects.exists())


class LinksTests(Fixture):
    def test_banner_and_reference_link_to_the_todo_page(self):
        BookingTask.objects.create(trip=self.trip, title="Seats")
        self.client.force_login(self.viewer)
        with mock.patch("apps.trips.views.django_timezone.localdate", return_value=date(2027, 9, 1)):
            html = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        banner = re.search(r'id="needs-attention">(.*?)</p>', html, re.S).group(1)
        self.assertIn('href="#other-todos">1 other to-do</a>', banner)  # covers nothing (booking-todos K2)
        self.assertNotIn("decision", banner)  # decisions are choices on the days now (D2)
        self.assertIn(f'href="{self.url}" data-all-todos>All to-dos</a>', html)

    def test_item_pages_add_a_todo_for_themselves(self):
        stay = Lodging.objects.create(trip=self.trip, name="Hotel", check_in=self.day4.date, check_out=date(2027, 9, 24))
        activity = TripActivity.objects.create(trip=self.trip, day=self.day4, title="Salt mine")
        task = make_task(self.trip, "Mine tickets", activity)
        new = reverse("trips:task_new", args=[self.trip.pk])
        self.client.force_login(self.editor)
        pages = {"leg": (reverse("trips:leg_edit", args=[self.trip.pk, self.leg.pk]), self.leg),
                 "stay": (reverse("trips:stay_edit", args=[self.trip.pk, stay.pk]), stay),
                 "activity": (reverse("trips:activity_edit", args=[self.trip.pk, self.day4.pk, activity.pk]), activity)}
        for kind, (url, item) in pages.items():
            with self.subTest(kind=kind):
                html = self.client.get(url).content.decode()
                self.assertIn(f'href="{new}?{kind}={item.pk}&amp;next=', html)
        html = self.client.get(pages["activity"][0]).content.decode()
        self.assertIn(reverse("trips:task_edit", args=[self.trip.pk, task.pk]) + "?next=", html)  # its to-do links
