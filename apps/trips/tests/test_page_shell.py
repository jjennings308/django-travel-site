"""The trip page's shell (docs/plans/trip-page-ux.md, U2): header and ⋯ menu, Overview,
collapsible days that open on the right day, and Reference as the home of confirmations."""
import re
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.trips.models import (BookingTask, Confirmation, Day, Lodging, TransportLeg, Trip, TripActivity,
                               TripGrant, TripRole)

User = get_user_model()
UTC = dt_timezone.utc
TODAY = "apps.trips.views.django_timezone.localdate"


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 17), end_date=date(2027, 9, 20),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.days = [Day.objects.create(trip=self.trip, day_number=n, date=date(2027, 9, 16 + n), theme=f"Theme {n}")
                     for n in range(1, 5)]
        self.url = reverse("trips:trip_detail", args=[self.trip.pk])

    def page(self, user=None, today=date(2027, 9, 18)):
        self.client.force_login(user or self.viewer)
        with mock.patch(TODAY, return_value=today):
            return self.client.get(self.url)

    def opened(self, response):
        return re.findall(r'<details class="day day-fold" id="(day-\d+)" open>', response.content.decode())


class OpenDayTests(Fixture):
    def test_today_during_the_trip_day_one_before_none_after(self):
        self.assertEqual(self.opened(self.page(today=date(2027, 9, 19))), ["day-3"])
        self.assertEqual(self.opened(self.page(today=date(2027, 8, 1))), ["day-1"])
        self.assertEqual(self.opened(self.page(today=date(2027, 10, 1))), [])

    def test_hash_links_open_their_day(self):
        html = self.page().content.decode()
        self.assertIn("data-days-toggle", html)  # Expand all / Collapse all
        self.assertIn('if (node.tagName === "DETAILS") node.open = true;', html)  # a #link opens its day
        self.assertIn('href="#day-2"', html)  # Overview rows link to their day


class HeaderTests(Fixture):
    def test_menu_holds_share_and_delete_only_for_those_allowed(self):
        share = reverse("trips:trip_share", args=[self.trip.pk])
        delete = reverse("trips:trip_delete", args=[self.trip.pk])
        html = self.page(self.editor).content.decode()
        self.assertIn(share, html)
        self.assertIn(delete, html)  # the editor created the trip
        self.assertIn(reverse("trips:trip_pdf", args=[self.trip.pk]), html)
        html = self.page(self.viewer).content.decode()
        for link in (share, delete, reverse("trips:trip_edit", args=[self.trip.pk])):
            self.assertNotIn(link, html)
        self.assertIn("data-trip-menu", html)  # Add to calendar is for everyone (R4)
        self.assertIn(reverse("trips:trip_calendar", args=[self.trip.pk]), html)
        self.trip.enable_public()
        html = self.page(self.viewer).content.decode()
        self.assertIn(reverse("public_trip", args=[self.trip.public_token]), html)  # the shared link, to copy
        self.assertNotIn(reverse("trips:trip_unshare", args=[self.trip.pk]), html)


class OverviewTests(Fixture):
    def test_rows_sleeping_overnight_travel_highlights_and_attention(self):
        d1, d2, d3, _d4 = self.days
        TransportLeg.objects.create(trip=self.trip, mode="plane", origin="PIT", destination="FRA",
                                    origin_timezone="America/New_York", destination_timezone="Europe/Berlin",
                                    departure_at=datetime(2027, 9, 17, 22, 0, tzinfo=UTC),
                                    arrival_at=datetime(2027, 9, 18, 6, 0, tzinfo=UTC))
        for origin, destination, order in (("Butzbach", "Frankfurt", 0), ("Frankfurt", "Marburg", 1)):
            TransportLeg.objects.create(trip=self.trip, mode="train", origin=origin, destination=destination,
                                        date=d3.date, est_duration=timedelta(minutes=45), order=order)
        hof = Lodging.objects.create(trip=self.trip, name="Hessischer Hof", check_in=d2.date, check_out=d3.date)
        Lodging.objects.create(trip=self.trip, name="Early Inn", check_in=date(2027, 9, 10),
                               check_out=date(2027, 9, 11))
        TripActivity.objects.create(trip=self.trip, day=d3, kind="tour", title="Student guide", start_time=time(15))
        BookingTask.objects.create(trip=self.trip, title="Hof rooms", stay=hof)
        page = self.page()
        html = page.content.decode()
        by_day = {day.day_number: day for day in page.context["days"]}
        self.assertTrue(by_day[1].overnight)
        self.assertIsNone(by_day[1].stay)
        self.assertEqual(by_day[1].travel_summary, "PIT → FRA")
        self.assertEqual(by_day[2].stay, hof)
        self.assertEqual(by_day[2].attention, 1)  # the stay's task, on its check-in day
        self.assertEqual((by_day[3].travel_icons, by_day[3].travel_summary), ("🚆", "2 legs · ~1 h 30 min"))
        self.assertEqual(by_day[3].highlights, ["Student guide"])
        self.assertEqual(by_day[4].highlights, ["Theme 4"])
        self.assertIn("✈ overnight", html)
        self.assertIn(f'id="stay-{hof.pk}"', html)  # the stay's card, on its check-in day
        self.assertIn("Stays outside the trip's days", html)  # Early Inn has no day to live on
        self.assertIn('href="#still-to-book">1 to do</a>', html)


class ReferenceTests(Fixture):
    def test_confirmation_row_once_with_chips_linking_to_it(self):
        leg = TransportLeg.objects.create(trip=self.trip, mode="train", origin="A", destination="B",
                                          date=self.days[2].date)
        conf = Confirmation.attach_number(self.trip, "DB-123", leg, provider="DB")
        html = self.page().content.decode()
        self.assertEqual(html.count(f'id="confirmation-{conf.pk}"'), 1)
        self.assertIn(f'href="#confirmation-{conf.pk}"', html)
        row = html[html.index(f'id="confirmation-{conf.pk}"'):]
        self.assertIn(f'href="#leg-{leg.pk}"', row[:2000])  # what it covers links back to the leg
        self.assertNotIn("Quick reference", html)
