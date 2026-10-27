"""Help links where people need them (help-center plan H4): every /help/ link on the trip page,
the edit pages and the account menu points at an existing guide and heading. Renaming a heading
or removing a guide fails here."""
import re
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.pages import helpdocs
from apps.pages.tests.test_help import link_ok
from apps.trips.models import Day, Lodging, Section, TransportLeg, Trip, TripActivity, TripGrant, TripRole

User = get_user_model()
HELP_HREF = re.compile(r'href="(/help/[^"]*)"')


class HelpLinkTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 20), end_date=date(2027, 9, 21),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 20))
        self.leg = TransportLeg.objects.create(trip=self.trip, origin="Frankfurt", destination="Augsburg",
                                               date=self.day.date)
        self.activity = TripActivity.objects.create(trip=self.trip, day=self.day, title="Fuggerei")
        self.section = Section.objects.create(day=self.day, section_type="logistics_table", title="Trains",
                                              content={"columns": ["Leg"], "rows": [["A → B"]]})
        self.stay = Lodging.objects.create(trip=self.trip, name="Hotel Augusta", check_in=self.day.date,
                               check_out=date(2027, 9, 21))
        self.client.force_login(self.editor)

    def help_links(self, url):
        with mock.patch("apps.trips.views.django_timezone.localdate", return_value=date(2027, 9, 1)):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return HELP_HREF.findall(response.content.decode())

    def test_every_help_link_resolves_and_each_page_has_its_own(self):
        guides = helpdocs.all_guides()
        trip = self.trip.pk
        expected = {
            reverse("trips:trip_detail", args=[trip]): {
                "/help/reading-your-trip/#days-at-a-glance",
                "/help/reading-your-trip/#reference", "/help/reading-your-trip/#booklet"},
            reverse("trips:trip_settings", args=[trip]): {"/help/starting-a-trip/"},
            reverse("trips:day_edit", args=[trip, self.day.pk]): {"/help/adding-a-day/"},
            reverse("trips:trip_todo", args=[trip]): {"/help/bookings-and-confirmations/#the-to-do-page"},
            reverse("trips:task_new", args=[trip]): {"/help/bookings-and-confirmations/#the-to-do-page"},
            reverse("trips:stay_edit", args=[trip, self.stay.pk]): {
                "/help/adding-a-day/#stays", "/help/bookings-and-confirmations/", "/help/contacts-and-info/"},
            reverse("trips:leg_edit", args=[trip, self.leg.pk]): {
                "/help/travel-legs/", "/help/bookings-and-confirmations/", "/help/contacts-and-info/"},
            reverse("trips:activity_edit", args=[trip, self.day.pk, self.activity.pk]): {
                "/help/bookings-and-confirmations/", "/help/contacts-and-info/"},
            reverse("trips:trip_tidy", args=[trip]): {"/help/tidying-an-itinerary/"},
            reverse("trips:trip_people", args=[trip]): {"/help/sharing-and-access/#who-can-do-what"},
            reverse("trips:trip_calendar", args=[trip]): {"/help/calendar-feed/"},
            reverse("trips:trip_history", args=[trip]): {"/help/trip-history/"},
            reverse("pages:dashboard"): {"/help/"},  # the account menu
        }
        for url, wanted in expected.items():
            with self.subTest(page=url):
                links = self.help_links(url)
                self.assertLessEqual(wanted, set(links))
                for href in links:
                    self.assertTrue(href == "/help/" or link_ok(href, guides), f"{href} on {url}")

    def test_help_links_are_never_printed(self):
        html = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        for tag in re.findall(r'<a class="help-link[^"]*"', html):
            self.assertIn("print:hidden", tag)
