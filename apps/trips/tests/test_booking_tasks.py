"""Phase E of docs/plans/trip-items-and-confirmations.md: booking tasks point at the leg or
stay they're about, suggestions for existing tasks, the derived "Not booked yet" list, and the
offer to tick tasks off when an item gets its first confirmation."""
from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.trips.forms import BookingTaskForm
from apps.trips.models import BookingTask, Confirmation, Day, Lodging, TransportLeg, Trip, TripGrant, TripRole

User = get_user_model()


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 18), end_date=date(2027, 9, 25),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.day = Day.objects.create(trip=self.trip, day_number=4, date=date(2027, 9, 20))
        self.ice = TransportLeg.objects.create(trip=self.trip, date=self.day.date, mode="train", operator="DB ICE",
                                               origin="Frankfurt Hof", destination="Augsburg Hof")
        self.ubahn = TransportLeg.objects.create(trip=self.trip, date=self.day.date, mode="train",
                                                 origin="München Hbf", destination="Theresienwiese", order=1)
        self.hof = Lodging.objects.create(trip=self.trip, name="Hessischer Hof", check_in=date(2027, 9, 18),
                                          check_out=date(2027, 9, 20))
        self.detail = reverse("trips:trip_detail", args=[self.trip.pk])

    def page(self, user=None):
        self.client.force_login(user or self.editor)
        return self.client.get(self.detail)


class ModelAndFormTests(Fixture):
    def test_one_item_at_most(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            BookingTask.objects.create(trip=self.trip, title="x", leg=self.ice, stay=self.hof)

    def test_form_refuses_both_and_another_trips_leg(self):
        other = Trip.objects.create(name="Other", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        theirs = TransportLeg.objects.create(trip=other, origin="X", destination="Y", date=date(2027, 1, 1))
        base = {"title": "Seats", "priority": "2"}

        def form(**data):
            return BookingTaskForm({**base, **data}, instance=BookingTask(trip=self.trip), trip=self.trip)

        self.assertFalse(form(leg=self.ice.pk, stay=self.hof.pk).is_valid())
        foreign = form(leg=theirs.pk)
        self.assertFalse(foreign.is_valid())
        self.assertIn("leg", foreign.errors)
        ok = form(leg=self.ice.pk)
        self.assertTrue(ok.is_valid(), ok.errors)


class TripPageTests(Fixture):
    def test_task_shown_on_its_item_and_names_it(self):
        BookingTask.objects.create(trip=self.trip, title="ICE seats for 6", leg=self.ice)
        page = self.page(self.viewer)
        self.assertContains(page, "Still to book: ICE seats for 6")
        self.assertContains(page, f'For: <a class="link-quiet" href="#leg-{self.ice.pk}">Frankfurt Hof → Augsburg Hof</a> · Day 4')

    def test_suggestions_link_and_dismiss(self):
        ice_task = BookingTask.objects.create(trip=self.trip, title="ICE train seats Frankfurt→Augsburg (6 people)")
        hotel_task = BookingTask.objects.create(trip=self.trip, title="Hotel Hessischer Hof, Butzbach")
        BookingTask.objects.create(trip=self.trip, title="Oktoberfest tent reservation")
        page = self.page()
        self.assertContains(page, "Looks like: Frankfurt Hof → Augsburg Hof (leg)")
        self.assertContains(page, "Looks like: Hessischer Hof (stay)")
        self.assertContains(page, "Looks like:", count=2)
        self.assertNotContains(self.page(self.viewer), "Looks like:")  # editors only

        link = reverse("trips:task_link", args=[self.trip.pk, ice_task.pk])
        self.client.force_login(self.editor)
        self.client.post(link, {"leg": self.ice.pk})
        ice_task.refresh_from_db()
        self.assertEqual(ice_task.leg, self.ice)
        self.client.post(reverse("trips:task_link", args=[self.trip.pk, hotel_task.pk]),
                         {"dismiss": "Hessischer Hof"})
        hotel_task.refresh_from_db()
        self.assertIsNone(hotel_task.stay)
        page = self.page()
        self.assertNotContains(page, "Looks like:")
        self.assertNotContains(page, "Not about:")  # the remembered dismissal isn't shown

    def test_no_suggestion_when_two_items_match(self):
        Lodging.objects.create(trip=self.trip, name="Hessischer Hof Annex", check_in=date(2027, 9, 18),
                               check_out=date(2027, 9, 19))
        BookingTask.objects.create(trip=self.trip, title="Hessischer Hof Annex rooms")
        self.assertNotContains(self.page(), "Looks like:")

    def test_link_permissions(self):
        task = BookingTask.objects.create(trip=self.trip, title="ICE seats Frankfurt Augsburg")
        link = reverse("trips:task_link", args=[self.trip.pk, task.pk])
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(link, {"leg": self.ice.pk}).status_code, 403)
        self.client.force_login(User.objects.create_user("st", "st@example.com", "pw-1234-abcd"))
        self.assertEqual(self.client.post(link, {"leg": self.ice.pk}).status_code, 404)

    def test_not_booked_yet(self):
        flight = TransportLeg.objects.create(trip=self.trip, date=self.day.date, mode="plane", origin="MUC",
                                             destination="MAN", order=2)
        booked = Lodging.objects.create(trip=self.trip, name="The Christopher", check_in=date(2027, 9, 21),
                                        check_out=date(2027, 9, 22))
        Confirmation.objects.create(trip=self.trip, confirmation_number="CHR1").link(booked)
        BookingTask.objects.create(trip=self.trip, title="Hof rooms", stay=self.hof)
        items = self.page().context["not_booked"]
        self.assertEqual([nb["item"] for nb in items], [self.ice, flight])  # U-Bahn, booked stay, tasked stay out


class OfferTests(Fixture):
    def setUp(self):
        super().setUp()
        self.seats = BookingTask.objects.create(trip=self.trip, title="ICE seats for 6", leg=self.ice)
        self.other = BookingTask.objects.create(trip=self.trip, title="Seat map check", leg=self.ice)
        self.client.force_login(self.editor)

    def test_first_confirmation_offers_its_tasks_and_ticks_only_the_chosen(self):
        response = self.client.post(reverse("trips:item_confirmations", args=[self.trip.pk, "leg", self.ice.pk]), {
            "action": "add", "confirmation_number": "DB123"})
        self.assertTrue(response["Location"].startswith(reverse("trips:task_offer", args=[self.trip.pk])))
        offer = self.client.get(response["Location"])
        self.assertContains(offer, "ICE seats for 6")
        self.assertContains(offer, "Seat map check")
        done = self.client.post(reverse("trips:task_offer", args=[self.trip.pk]), {
            "tasks": f"{self.seats.pk},{self.other.pk}", "done": [self.seats.pk], "next": self.detail})
        self.assertRedirects(done, self.detail, fetch_redirect_response=False)
        self.seats.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual((self.seats.done, self.other.done), (True, False))

    def test_no_offer_for_a_second_confirmation(self):
        Confirmation.objects.create(trip=self.trip, confirmation_number="FIRST").link(self.ice)
        second = Confirmation.objects.create(trip=self.trip, confirmation_number="SECOND")
        response = self.client.post(reverse("trips:item_confirmations", args=[self.trip.pk, "leg", self.ice.pk]),
                                    {"action": "attach", "confirmation": second.pk})
        self.assertNotIn("tasks/done", response["Location"])

    def test_attaching_an_existing_one_offers_too(self):
        conf = Confirmation.objects.create(trip=self.trip, confirmation_number="DB123")
        response = self.client.post(reverse("trips:item_confirmations", args=[self.trip.pk, "leg", self.ice.pk]),
                                    {"action": "attach", "confirmation": conf.pk})
        self.assertIn("tasks/done", response["Location"])

    def test_offer_ignores_other_trips_tasks(self):
        other = Trip.objects.create(name="Other", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        theirs = BookingTask.objects.create(trip=other, title="Not yours")
        self.client.post(reverse("trips:task_offer", args=[self.trip.pk]),
                         {"tasks": str(theirs.pk), "done": [theirs.pk], "next": self.detail})
        theirs.refresh_from_db()
        self.assertFalse(theirs.done)
