"""Activities on a day (TripActivity): tours, timed entries, tickets, tables, car hire, with
confirmations and booking tasks attached like any other item."""
from datetime import date, time
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import POI, City, Country
from apps.trips.models import (BookingTask, Confirmation, Day, TransportLeg, Traveler, Trip, TripActivity,
                               TripGrant, TripRole)
from apps.trips.public import public_trip

User = get_user_model()


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 24), end_date=date(2027, 9, 25),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.day = Day.objects.create(trip=self.trip, day_number=8, date=date(2027, 9, 24))
        de = Country.objects.create(name="Germany", slug="de", iso_code="DE", iso3_code="DEU", continent="Europe",
                                    approval_status=ApprovalStatus.APPROVED)
        self.schwangau = City.objects.create(name="Schwangau", slug="schwangau", country=de, latitude=47.57,
                                             longitude=10.73, approval_status=ApprovalStatus.APPROVED)
        elsewhere = City.objects.create(name="Paris", slug="paris", country=de, latitude=48.8, longitude=2.3,
                                        approval_status=ApprovalStatus.APPROVED)
        self.castle = POI.objects.create(name="Neuschwanstein Castle", slug="neuschwanstein", city=self.schwangau,
                                         latitude=47.55, longitude=10.75,
                                         approval_status=ApprovalStatus.APPROVED)
        self.louvre = POI.objects.create(name="Louvre", slug="louvre", city=elsewhere, latitude=48.86,
                                         longitude=2.33, approval_status=ApprovalStatus.APPROVED)
        self.trip.cities.add(self.schwangau)
        self.sara = Traveler.objects.create(name="Sara Test")
        self.trip.travelers.add(self.sara)
        self.new_url = reverse("trips:activity_new", args=[self.trip.pk, self.day.pk])

    def tour(self, **kwargs):
        return TripActivity.objects.create(trip=self.trip, day=self.day, **{
            "kind": "entry", "title": "Neuschwanstein timed entry", "start_time": time(10, 30), **kwargs})


class EditingTests(Fixture):
    def test_add_from_the_day_page_then_confirm_on_its_page(self):
        self.client.force_login(self.editor)
        self.assertContains(self.client.get(reverse("trips:day_edit", args=[self.trip.pk, self.day.pk])), self.new_url)
        form = self.client.get(self.new_url).context["form"]
        self.assertEqual(list(form.fields["poi"].queryset), [self.castle])  # the trip's cities only
        response = self.client.post(self.new_url, {
            "kind": "entry", "title": "Neuschwanstein timed entry", "provider": "Ticket Center Hohenschwangau",
            "start_time": "10:30", "end_time": "11:15", "poi": self.castle.pk, "travelers": [self.sara.pk],
            "est_cost": "21.00", "currency": "EUR", "notes": "Collect tickets 1 hr before", "order": ""})
        activity = TripActivity.objects.get()
        self.assertTrue(response["Location"].startswith(
            reverse("trips:activity_edit", args=[self.trip.pk, self.day.pk, activity.pk])))
        self.assertEqual((activity.time_range, activity.place_name), ("10:30 AM – 11:15 AM", "Neuschwanstein Castle"))
        page = self.client.get(response["Location"])
        self.assertContains(page, reverse("trips:item_confirmations", args=[self.trip.pk, "activity", activity.pk]))

    def test_refuses_another_citys_place_and_end_before_start(self):
        self.client.force_login(self.editor)
        page = self.client.post(self.new_url, {"kind": "tour", "title": "X", "poi": self.louvre.pk,
                                               "start_time": "11:00", "end_time": "10:00"})
        self.assertEqual(set(page.context["form"].errors), {"poi", "end_time"})
        self.assertFalse(TripActivity.objects.exists())

    def test_permissions(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.new_url).status_code, 403)
        self.client.force_login(User.objects.create_user("st", "st@example.com", "pw-1234-abcd"))
        self.assertEqual(self.client.get(self.new_url).status_code, 404)

    def test_delete_keeps_its_confirmation(self):
        activity = self.tour()
        conf = Confirmation.attach_number(self.trip, "NEU-123", activity, provider="Ticket Center")
        self.client.force_login(self.editor)
        self.client.post(reverse("trips:activity_delete", args=[self.trip.pk, self.day.pk, activity.pk]))
        self.assertFalse(TripActivity.objects.exists())
        self.assertEqual(Confirmation.objects.get().pk, conf.pk)
        self.assertFalse(conf.links.exists())


class ShowingTests(Fixture):
    def test_on_its_day_with_confirmation_and_in_quick_reference(self):
        activity = self.tour(poi=self.castle)
        activity.travelers.add(self.sara)
        Confirmation.attach_number(self.trip, "NEU-123", activity, provider="Ticket Center")
        self.client.force_login(self.viewer)
        page = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        html = page.content.decode()
        self.assertIn(f'id="activity-{activity.pk}"', html)
        self.assertIn("10:30 AM", html)
        self.assertIn("For Sara Test", html)
        self.assertIn("NEU-123 · Ticket Center", html)
        self.assertEqual([title for title, _ in page.context["confirmation_groups"]], ["Activities"])
        self.assertNotIn(reverse("trips:activity_new", args=[self.trip.pk, self.day.pk]), html)  # no adding here

    def test_in_the_pdf_and_never_public(self):
        self.tour()
        captured = {}

        def fake(html, base_url):
            captured["html"] = html
            return b"%PDF"

        self.client.force_login(self.viewer)
        with mock.patch("apps.trips.pdf.render_pdf", side_effect=fake):
            self.client.get(reverse("trips:trip_pdf", args=[self.trip.pk]))
        self.assertIn("Neuschwanstein timed entry", captured["html"])
        self.trip.enable_public()
        self.assertNotIn("Neuschwanstein timed entry", str(public_trip(self.trip)))

    def test_its_confirmations_are_reached_from_its_day(self):
        activity = self.tour()
        self.client.force_login(self.editor)
        page = self.client.get(reverse("trips:day_edit", args=[self.trip.pk, self.day.pk]))  # E3: not Edit trip
        self.assertContains(page, reverse("trips:item_confirmations", args=[self.trip.pk, "activity", activity.pk]))


class TaskTests(Fixture):
    def test_a_task_covers_an_activity_and_a_leg(self):
        activity = self.tour()
        leg = TransportLeg.objects.create(trip=self.trip, origin="A", destination="B", date=self.day.date)
        task = BookingTask.objects.create(trip=self.trip, title="x")
        task.link(leg)
        task.link(activity)
        self.assertEqual(task.covered(), [leg, activity])

    def test_suggested_by_title_linked_and_offered_on_first_confirmation(self):
        activity = self.tour()
        task = BookingTask.objects.create(trip=self.trip, title="Neuschwanstein timed entry (Fri Sept 24)")
        self.client.force_login(self.editor)
        detail = reverse("trips:trip_detail", args=[self.trip.pk])
        self.assertContains(self.client.get(detail), "Looks like: Neuschwanstein timed entry (activity)")
        self.assertEqual([nb["item"] for nb in self.client.get(detail).context["not_booked"]], [activity])
        self.client.post(reverse("trips:task_link", args=[self.trip.pk, task.pk]), {"activity": activity.pk})
        self.assertEqual(task.covered(), [activity])
        self.assertEqual(self.client.get(detail).context["not_booked"], [])  # it has a task now
        response = self.client.post(reverse("trips:item_confirmations", args=[self.trip.pk, "activity", activity.pk]),
                                    {"action": "add", "confirmation_number": "NEU-123"})
        self.assertIn("tasks/done", response["Location"])

    def test_not_booked_skips_other_kinds(self):
        self.tour(kind="other", title="Stroll by the Alpsee")
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).context["not_booked"], [])
