"""A to-do covers several items (docs/plans/booking-todos.md, K1): ``TaskLink``, the cover label, partners,
Same booking as the way out, the confirmation offer and the migration that copied the old FKs."""
from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase
from django.urls import reverse

from apps.core.testing import RestoringTransactionTestCase
from apps.trips import booking_tasks, changes
from apps.trips.forms import TransportLegForm
from apps.trips.models import (BookingTask, Confirmation, Day, Lodging, TaskLink, TransportLeg, Trip, TripGrant,
                               TripRole)
from apps.trips.tests.helpers import make_task

User = get_user_model()


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Bavaria", start_date=date(2027, 9, 20), end_date=date(2027, 9, 25),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        self.day1 = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 20))
        self.day3 = Day.objects.create(trip=self.trip, day_number=3, date=date(2027, 9, 22))
        self.out = self.leg("Augsburg Hbf", "München Hbf", date(2027, 9, 20), order=1)
        self.back = self.leg("München Hbf", "Augsburg Hbf", date(2027, 9, 22), order=1)
        self.hotel = Lodging.objects.create(trip=self.trip, name="Hotel Laimer Hof", check_in=date(2027, 9, 20),
                                            check_out=date(2027, 9, 22))

    def leg(self, origin, destination, when, mode="train", **fields):
        return TransportLeg.objects.create(trip=self.trip, mode=mode, operator="DB", origin=origin,
                                           destination=destination, date=when, **fields)

    def attached(self):
        """The trip as the page sees it: legs, stays, tasks with their links, then ``attach``."""
        from django.db.models import prefetch_related_objects
        trip = Trip.objects.get(pk=self.trip.pk)
        prefetch_related_objects([trip], "transport", "lodging", "days", "booking_tasks__links")
        from apps.trips.views import _attach_confirmations
        _attach_confirmations(trip)
        booking_tasks.attach(trip)
        return trip


class LabelAndPartnerTests(Fixture):
    def test_cover_label(self):
        self.assertEqual(booking_tasks.cover_label([self.out, self.back]), "Augsburg Hbf → München Hbf and back")
        pit = self.leg("PIT", "ATL", date(2027, 9, 20), mode="plane", order=2)
        atl = self.leg("ATL", "FRA", date(2027, 9, 20), mode="plane", order=3)
        self.assertEqual(booking_tasks.cover_label([pit, atl]), "PIT → ATL → FRA")
        self.assertEqual(booking_tasks.cover_label([self.hotel, self.out]), "Hotel Laimer Hof + 1 more")
        self.assertEqual(booking_tasks.cover_label([self.hotel]), "Hotel Laimer Hof")

    def test_partners_are_the_way_back_and_the_connections(self):
        pit = self.leg("PIT", "ATL", date(2027, 9, 20), mode="plane", order=2)
        atl = self.leg("ATL", "FRA", date(2027, 9, 20), mode="plane", order=3)
        legs = list(TransportLeg.objects.filter(trip=self.trip))
        self.assertEqual(booking_tasks.partners(self.out, legs), [(self.back, "the way back")])
        self.assertEqual(booking_tasks.partners(self.back, legs), [])  # only a later leg is "the way back"
        self.assertEqual(booking_tasks.partners(pit, legs), [(atl, "connection")])
        self.assertEqual(booking_tasks.partners(atl, legs), [(pit, "connection")])
        self.assertEqual(booking_tasks.partners(self.hotel, legs), [])


class PageTests(Fixture):
    def test_one_todo_on_both_legs_empties_not_booked_for_both(self):
        before = [entry["item"] for entry in booking_tasks.not_booked(self.attached())]
        self.assertIn(self.out, before)
        self.assertIn(self.back, before)
        make_task(self.trip, "Set up train travel", self.out, self.back)
        trip = self.attached()
        after = [entry["item"] for entry in booking_tasks.not_booked(trip)]
        self.assertNotIn(self.out, after)
        self.assertNotIn(self.back, after)
        task = next(iter(trip.booking_tasks.all()))
        self.assertEqual((task.item, task.cover_label, task.item_day), (self.out, "Augsburg Hbf → München Hbf and back",
                                                                       self.day1))
        legs = {leg.pk: leg for leg in trip.transport.all()}
        self.assertEqual([t.title for t in legs[self.back.pk].open_tasks], ["Set up train travel"])  # on every item

    def test_the_trip_page_shows_the_cover_label(self):
        make_task(self.trip, "Set up train travel", self.out, self.back)
        self.client.force_login(self.editor)
        html = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        row = html[html.index(f'id="to-book-leg-{self.out.pk}"'):]
        row = row[:row.index("</li>")]
        self.assertIn(">Augsburg Hbf → München Hbf and back</a>", row)  # one To book row for both (K2)
        self.assertIn("Set up train travel", row)
        self.assertNotIn(f'id="to-book-leg-{self.back.pk}"', html)
        self.assertEqual(html.count("Still to book: Set up train travel"), 2)

    def test_deleting_a_leg_deletes_its_link_not_the_todo(self):
        task = make_task(self.trip, "Set up train travel", self.out, self.back)
        self.back.delete()
        self.assertEqual(task.covered(), [self.out])
        self.assertTrue(BookingTask.objects.filter(pk=task.pk).exists())

    def test_a_pre_k1_snapshot_restores_as_a_link(self):
        task = make_task(self.trip, "Seats")
        snap = changes.snapshot(self.back)
        snap.pop("task_links")
        snap["tasks"] = [task.pk]  # how a snapshot taken before K1 kept it
        change = changes.record(self.trip.pk, "removed", "Removed the way back", self.back, before=snap)
        self.back.delete()
        pk = change.item_id
        changes.restore(change, self.editor)
        self.assertEqual([item.pk for item in task.covered()], [pk])


class FormTests(Fixture):
    def test_adding_from_a_leg_ticks_it_and_its_way_back(self):
        self.client.force_login(self.editor)
        page = self.client.get(reverse("trips:task_new", args=[self.trip.pk]) + f"?leg={self.out.pk}")
        self.assertEqual(page.context["form"].initial["covers"], sorted([f"leg-{self.out.pk}", f"leg-{self.back.pk}"]))
        html = page.content.decode()
        self.assertIn("Also ticked: München Hbf → Augsburg Hbf (the way back)", html)
        self.assertIn(f'value="leg-{self.back.pk}" class="mt-1" checked', html)
        self.assertIn(f'value="stay-{self.hotel.pk}" class="mt-1">', html)  # not a partner
        self.assertIn("Day 1 · Mon Sep 20", html)

    def test_repeated_items_tick_each(self):
        self.client.force_login(self.editor)
        url = reverse("trips:task_new", args=[self.trip.pk]) + f"?stay={self.hotel.pk}&leg={self.back.pk}"
        self.assertEqual(self.client.get(url).context["form"].initial["covers"],
                         sorted([f"stay-{self.hotel.pk}", f"leg-{self.back.pk}"]))


class SameBookingTests(Fixture):
    def form(self, **over):
        data = {"mode": "train", "origin": "Augsburg Hbf", "destination": "München Hbf", "date": "2027-09-20",
                "operator": "DB", "origin_timezone": "Europe/Berlin", "destination_timezone": "Europe/Berlin",
                "currency": "EUR", "add_return": "on", "return_date": "2027-09-23", "order": "1"}
        data.update(over)
        return TransportLegForm(data, instance=self.out)

    def test_ticked_by_default_when_the_way_out_has_a_todo_or_confirmation(self):
        self.assertFalse(TransportLegForm(instance=self.out).initial.get("same_booking"))
        make_task(self.trip, "Set up train travel", self.out)
        self.assertTrue(TransportLegForm(instance=self.out).initial["same_booking"])

    def test_the_return_joins_the_way_outs_todos_and_confirmations(self):
        task = make_task(self.trip, "Set up train travel", self.out)
        done = make_task(self.trip, "Old one", self.out, done=True)
        confirmation = Confirmation.attach_number(self.trip, "GCH7JS", self.out)
        form = self.form(same_booking="on")
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        back = form.return_leg
        self.assertIn(back, task.covered())
        self.assertNotIn(back, done.covered())  # only open to-dos
        self.assertIn(back, confirmation.covered_items())

    def test_unticked_links_nothing(self):
        task = make_task(self.trip, "Set up train travel", self.out)
        Confirmation.attach_number(self.trip, "GCH7JS", self.out)
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(task.covered(), [self.out])
        self.assertFalse(form.return_leg.confirmation_links.exists())


class ConfirmationOfferTests(Fixture):
    def setUp(self):
        super().setUp()
        self.task = make_task(self.trip, "Set up train travel", self.out, self.back)
        self.client.force_login(self.editor)

    def add(self, leg, number="GCH7JS"):
        url = reverse("trips:item_confirmations", args=[self.trip.pk, "leg", leg.pk])
        return self.client.post(url, {"confirmation_number": number, "provider": "", "label": ""})

    def test_the_other_legs_are_offered_the_number_then_the_todo(self):
        response = self.add(self.out)
        spread = reverse("trips:confirmation_spread", args=[self.trip.pk, Confirmation.objects.get().pk])
        self.assertTrue(response["Location"].startswith(spread))
        page = self.client.get(response["Location"]).content.decode()
        self.assertIn("Also attach GCH7JS to:", page)
        self.assertIn(f'name="attach" value="leg-{self.back.pk}" checked', page)
        self.assertFalse(self.back.confirmation_links.exists())  # offered, not linked
        query = response["Location"].split("?", 1)[1]
        from urllib.parse import parse_qs
        data = {k: v[0] for k, v in parse_qs(query).items()}
        after = self.client.post(spread, {**data, "attach": f"leg-{self.back.pk}"})
        self.assertTrue(self.back.confirmation_links.exists())
        self.assertIn(reverse("trips:task_offer", args=[self.trip.pk]), after["Location"])
        self.assertIn(f"tasks={self.task.pk}", after["Location"])

    def test_not_these_links_nothing_and_offers_no_task(self):
        response = self.add(self.out)
        from urllib.parse import parse_qs
        data = {k: v[0] for k, v in parse_qs(response["Location"].split("?", 1)[1]).items()}
        spread = response["Location"].split("?", 1)[0]
        after = self.client.post(spread, {**data, "attach": f"leg-{self.back.pk}", "skip": "1"})
        self.assertFalse(self.back.confirmation_links.exists())
        self.assertNotIn("task_offer", after["Location"])
        self.assertNotIn("/tasks/done/", after["Location"])

    def test_offer_for_only_when_every_item_is_confirmed(self):
        before = booking_tasks.confirmed_items(self.trip)
        Confirmation.attach_number(self.trip, "GCH7JS", self.out)
        self.assertEqual(booking_tasks.offer_for(self.trip, before), [])
        before = booking_tasks.confirmed_items(self.trip)
        Confirmation.attach_number(self.trip, "GCH7JS", self.back)
        self.assertEqual(booking_tasks.offer_for(self.trip, before), [self.task])


class CopyMigrationTests(RestoringTransactionTestCase):
    """trips 0056–0058: each to-do's leg / stay / activity becomes a link."""

    BEFORE = [("trips", "0055_remove_decision_todos")]
    AFTER = []  # all the way: the test reads through today's models (0059 added no_booking)

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        pinned = dict(targets)
        nodes = [(app, pinned.get(app, name)) for app, name in executor.loader.graph.leaf_nodes()]
        executor.migrate(nodes)
        executor.loader.build_graph()
        return executor.loader.project_state(nodes).apps

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def test_each_fk_becomes_a_link(self):
        apps = self.migrate(self.BEFORE)
        Trip = apps.get_model("trips", "Trip")
        Day = apps.get_model("trips", "Day")
        Leg = apps.get_model("trips", "TransportLeg")
        Stay = apps.get_model("trips", "Lodging")
        Activity = apps.get_model("trips", "TripActivity")
        Task = apps.get_model("trips", "BookingTask")
        trip = Trip.objects.create(name="Old trip", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        day = Day.objects.create(trip=trip, day_number=1, date=date(2027, 1, 1))
        leg = Leg.objects.create(trip=trip, origin="A", destination="B", date=date(2027, 1, 1))
        stay = Stay.objects.create(trip=trip, name="Inn", check_in=date(2027, 1, 1), check_out=date(2027, 1, 2))
        activity = Activity.objects.create(trip=trip, day=day, title="Tour")
        tasks = {"leg": Task.objects.create(trip=trip, title="a", leg=leg).pk,
                 "stay": Task.objects.create(trip=trip, title="b", stay=stay).pk,
                 "activity": Task.objects.create(trip=trip, title="c", activity=activity).pk}
        loose = Task.objects.create(trip=trip, title="d").pk
        self.migrate(self.AFTER)
        self.assertEqual([i.pk for i in BookingTask.objects.get(pk=tasks["leg"]).covered()], [leg.pk])
        self.assertEqual([i.pk for i in BookingTask.objects.get(pk=tasks["stay"]).covered()], [stay.pk])
        self.assertEqual([i.pk for i in BookingTask.objects.get(pk=tasks["activity"]).covered()], [activity.pk])
        self.assertFalse(TaskLink.objects.filter(task_id=loose).exists())
