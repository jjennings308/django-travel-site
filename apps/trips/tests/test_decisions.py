"""Decisions as tasks with options (docs/plans/trip-page-ux.md, U6), no longer made or edited
(docs/plans/retire-decision-todos.md, D1): they show read-only and offer "Make it a choice"."""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.trips.models import BookingTask, Day, Lodging, TaskOption, Trip, TripActivity, TripGrant, TripRole

User = get_user_model()


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 20), end_date=date(2027, 9, 25),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.day = Day.objects.create(trip=self.trip, day_number=4, date=date(2027, 9, 20))
        self.task = BookingTask.objects.create(trip=self.trip, title="Augsburg accommodation", kind="decide",
                                               priority=1)
        self.augusta = TaskOption.objects.create(task=self.task, title="Hotel Augusta", order=2, est_cost=Decimal("140"),
                                                 currency="EUR", detail="Old town", url="https://example.com/a")
        self.mohren = TaskOption.objects.create(task=self.task, title="Drei Mohren", order=1)
        self.options_url = reverse("trips:task_options", args=[self.trip.pk, self.task.pk])

    def page(self, user=None):
        self.client.force_login(user or self.viewer)
        with mock.patch("apps.trips.views.django_timezone.localdate", return_value=date(2027, 9, 1)):
            return self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))

class ModelTests(Fixture):
    def test_one_chosen_per_task_and_options_keep_their_order(self):
        self.assertEqual(list(self.task.options.all()), [self.mohren, self.augusta])
        self.augusta.chosen = True
        self.augusta.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            TaskOption.objects.filter(pk=self.mohren.pk).update(chosen=True)


class PageTests(Fixture):
    def test_decision_lists_without_an_item_with_options_and_attention(self):
        response = self.page()
        html = response.content.decode()
        self.assertIn("Decide: Augsburg accommodation", html)
        self.assertLess(html.index("Drei Mohren"), html.index("Hotel Augusta"))  # option order
        self.assertIn("~140.00 EUR", html)
        self.assertIn(f'href="{reverse("trips:trip_todo", args=[self.trip.pk])}">1 decision</a>', html)  # E2
        convert = reverse("trips:trip_convert", args=[self.trip.pk]) + f"?task={self.task.pk}"
        self.assertNotIn(convert, html)  # viewers can't convert
        editor = self.page(self.editor).content.decode()
        self.assertIn(convert, editor)
        for retired in (self.options_url, "Add options", "Add as a stay", reverse("trips:option_add", args=[self.trip.pk, self.augusta.pk])):
            self.assertNotIn(retired, editor)


class OptionsPageTests(Fixture):
    def test_read_only_with_make_it_a_choice(self):
        self.client.force_login(self.editor)
        page = self.client.get(self.options_url).content.decode()
        self.assertIn("Hotel Augusta", page)
        self.assertNotIn('method="post"', page[page.index('<nav class="crumbs">'):])
        self.assertIn(reverse("trips:trip_convert", args=[self.trip.pk]) + f"?task={self.task.pk}", page)
        self.client.post(self.options_url, {"options-TOTAL_FORMS": "0", "chosen": str(self.augusta.pk)})
        self.augusta.refresh_from_db()
        self.assertFalse(self.augusta.chosen)  # nothing saved

    def test_no_entry_point_offers_options(self):
        plain = BookingTask.objects.create(trip=self.trip, title="Which tent")
        self.client.force_login(self.editor)
        pages = [reverse("trips:trip_todo", args=[self.trip.pk]),
                 reverse("trips:task_edit", args=[self.trip.pk, plain.pk]),
                 reverse("trips:task_edit", args=[self.trip.pk, self.task.pk])]
        for url in pages:
            html = self.client.get(url).content.decode()
            for retired in ("Add options", "Make it a decision", "Options (",
                            reverse("trips:task_options", args=[self.trip.pk, plain.pk])):
                self.assertNotIn(retired, html, url)
        self.assertIn("data-make-choice", self.client.get(pages[0]).content.decode())  # the one with options
        self.assertNotIn("data-make-choice", self.client.get(pages[1]).content.decode())

    def test_permissions(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.options_url).status_code, 403)
        self.client.force_login(User.objects.create_user("st", "st@example.com", "pw-1234-abcd"))
        self.assertEqual(self.client.get(self.options_url).status_code, 404)


class AddAsTests(Fixture):
    def test_add_as_a_stay_prefills_the_days_new_stay_and_saves_nothing(self):
        """No day on the task: the new-stay page of Day 1 (here the only day), pre-filled (E1)."""
        self.client.force_login(self.editor)
        response = self.client.get(reverse("trips:option_add", args=[self.trip.pk, self.augusta.pk]) + "?as=stay")
        self.assertIn(reverse("trips:stay_new", args=[self.trip.pk, self.day.pk]), response["Location"])
        form = self.client.get(response["Location"]).context["form"]
        self.assertEqual((form.initial["name"], form.initial["currency"]), ("Hotel Augusta", "EUR"))
        self.assertIn("https://example.com/a", form.initial["notes"])
        self.assertEqual(form.initial["check_in"], self.day.date)
        self.assertFalse(Lodging.objects.exists())

    def test_add_as_an_activity_prefills_the_days_new_activity(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse("trips:option_add", args=[self.trip.pk, self.augusta.pk]) + f"?day={self.day.pk}")
        self.assertIn(reverse("trips:activity_new", args=[self.trip.pk, self.day.pk]), response["Location"])
        form = self.client.get(response["Location"]).context["form"]
        self.assertEqual((form.initial["title"], form.initial["currency"]), ("Hotel Augusta", "EUR"))
        self.assertFalse(TripActivity.objects.exists())

    def test_another_trips_option_is_refused(self):
        other = Trip.objects.create(name="Other", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        theirs = TaskOption.objects.create(task=BookingTask.objects.create(trip=other, title="x"), title="y")
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(reverse("trips:option_add", args=[self.trip.pk, theirs.pk])).status_code, 404)
        page = self.client.get(reverse("trips:stay_new", args=[self.trip.pk, self.day.pk]) + f"?from_option={theirs.pk}")
        self.assertNotEqual(page.context["form"].initial.get("name"), "y")
