"""Decisions as tasks with options (docs/plans/trip-page-ux.md, U6)."""
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

    def options_post(self, chosen, **rows):
        page = self.client.get(self.options_url)
        formset = page.context["formset"]
        data = {"options-TOTAL_FORMS": str(len(formset.forms)), "options-INITIAL_FORMS": str(formset.initial_form_count()),
                "options-MIN_NUM_FORMS": "0", "options-MAX_NUM_FORMS": "1000", "chosen": chosen}
        for form in formset.forms:  # what a browser posts: every row's current values
            for name in form.fields:
                value = form[name].value()
                if value is not None and value is not False:
                    data[form.add_prefix(name)] = str(value)
        data.update(rows)
        return self.client.post(self.options_url, data)


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
        self.assertIn('href="#still-to-book">1 decision</a>', html)
        self.assertNotIn(self.options_url, html)  # viewers can't edit options
        self.assertIn(self.options_url, self.page(self.editor).content.decode())


class OptionsPageTests(Fixture):
    def test_choose_unchoose_and_add_an_option(self):
        self.client.force_login(self.editor)
        self.options_post(str(self.augusta.pk))
        self.augusta.refresh_from_db()
        self.assertTrue(self.augusta.chosen)
        self.options_post("")
        self.augusta.refresh_from_db()
        self.assertFalse(self.augusta.chosen)
        self.options_post("new-2", **{"options-2-title": "Airbnb Altstadt", "options-2-order": "3"})
        new = TaskOption.objects.get(title="Airbnb Altstadt")
        self.assertTrue(new.chosen)
        self.assertEqual(self.task.options.filter(chosen=True).count(), 1)

    def test_a_task_with_options_becomes_a_decision(self):
        plain = BookingTask.objects.create(trip=self.trip, title="Which tent")
        self.client.force_login(self.editor)
        self.options_url = reverse("trips:task_options", args=[self.trip.pk, plain.pk])
        self.options_post("", **{"options-0-title": "Schottenhamel", "options-0-order": "1"})
        plain.refresh_from_db()
        self.assertEqual(plain.kind, "decide")

    def test_permissions(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.options_url).status_code, 403)
        self.client.force_login(User.objects.create_user("st", "st@example.com", "pw-1234-abcd"))
        self.assertEqual(self.client.get(self.options_url).status_code, 404)


class AddAsTests(Fixture):
    def test_add_as_a_stay_prefills_edit_trip_and_saves_nothing(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse("trips:option_add", args=[self.trip.pk, self.augusta.pk]) + "?as=stay")
        page = self.client.get(response["Location"])
        lodging = dict((key, fs) for key, _label, fs in page.context["formsets"])["lodging"]
        blank = lodging.forms[-1]
        self.assertEqual(blank.initial["name"], "Hotel Augusta")
        self.assertIn("https://example.com/a", blank.initial["notes"])
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
        page = self.client.get(reverse("trips:trip_edit", args=[self.trip.pk]) + f"?stay_from_option={theirs.pk}")
        lodging = dict((key, fs) for key, _label, fs in page.context["formsets"])["lodging"]
        self.assertNotEqual(lodging.forms[-1].initial.get("name"), "y")
