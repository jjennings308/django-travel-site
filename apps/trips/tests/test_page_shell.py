"""The trip page's shell (docs/plans/trip-page-ux.md, U2; trip-days-as-overview.md): header and ⋯ menu,
the Needs attention banner, collapsible days whose summaries are the overview, About this trip, and
Reference as the home of confirmations."""
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
        return re.findall(r'<details class="day day-fold" id="(day-\d+)" open[ >]', response.content.decode())


class OpenDayTests(Fixture):
    def test_today_during_the_trip_day_one_before_none_after(self):
        self.assertEqual(self.opened(self.page(today=date(2027, 9, 19))), ["day-3"])
        self.assertEqual(self.opened(self.page(today=date(2027, 8, 1))), ["day-1"])
        self.assertEqual(self.opened(self.page(today=date(2027, 10, 1))), [])

    def test_hash_links_open_their_day(self):
        html = self.page().content.decode()
        self.assertIn("data-days-toggle", html)  # Expand all / Collapse all
        self.assertIn('if (node.tagName === "DETAILS") node.open = true;', html)  # a #link opens its day
        self.assertIn('if (id === "overview") id = "days";', html)  # old #overview links land on the days


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


def summary(html, number):
    """The <summary> of day N's fold."""
    found = re.search(rf'<details class="day day-fold" id="day-{number}"[^>]*>\s*<summary class="day-summary">(.*?)</summary>',
                      html, re.S)
    return found.group(1)


class DaySummaryTests(Fixture):
    def setUp(self):
        super().setUp()
        d1, d2, d3, _d4 = self.days
        TransportLeg.objects.create(trip=self.trip, mode="plane", origin="PIT", destination="FRA",
                                    origin_timezone="America/New_York", destination_timezone="Europe/Berlin",
                                    departure_at=datetime(2027, 9, 17, 22, 0, tzinfo=UTC),
                                    arrival_at=datetime(2027, 9, 18, 6, 0, tzinfo=UTC))
        for origin, destination, order in (("Butzbach", "Frankfurt", 0), ("Frankfurt", "Marburg", 1)):
            TransportLeg.objects.create(trip=self.trip, mode="train", origin=origin, destination=destination,
                                        date=d3.date, est_duration=timedelta(minutes=45), order=order)
        self.hof = Lodging.objects.create(trip=self.trip, name="Hessischer Hof", check_in=d2.date, check_out=d3.date)
        Lodging.objects.create(trip=self.trip, name="Early Inn", check_in=date(2027, 9, 10),
                               check_out=date(2027, 9, 11))
        TripActivity.objects.create(trip=self.trip, day=d3, kind="tour", title="Student guide", start_time=time(15))
        BookingTask.objects.create(trip=self.trip, title="Hof rooms", stay=self.hof)

    def test_the_old_overview_table_is_gone(self):
        html = self.page().content.decode()
        self.assertNotIn("trip-overview", html)
        self.assertNotIn('id="overview"', html)
        nav = re.search(r'<nav class="day-nav"[^>]*>(.*?)</nav>', html, re.S).group(1)
        self.assertEqual(re.findall(r'href="#([a-z-]+)"', nav), ["days", "reference"])

    def test_each_summary_carries_the_day_at_a_glance(self):
        page = self.page()
        html = page.content.decode()
        by_day = {day.day_number: day for day in page.context["days"]}
        self.assertEqual((by_day[1].travel_summary, by_day[2].stay, by_day[2].attention), ("PIT → FRA", self.hof, 1))
        one, two, three, four = (summary(html, n) for n in range(1, 5))
        self.assertIn("✈ overnight", one)
        self.assertIn("✈ PIT → FRA", one)
        self.assertNotIn("🛏", one)  # no stay that night: left out, no empty separator
        self.assertIn(f'🛏 <a class="link-quiet" href="#stay-{self.hof.pk}">Hessischer Hof</a> (check in)', two)
        self.assertIn('href="#needs-attention" title="Not booked or still to do">⚠1</a>', two)
        self.assertIn(f'href="#stay-{self.hof.pk}">Hessischer Hof</a> (check out)', three)
        self.assertIn("🚆 2 legs · ~1 h 30 min", three)
        self.assertIn("Student guide", three)
        self.assertIn("Theme 4", four)  # line 1 keeps the theme ...
        self.assertNotIn("data-day-glance", four)  # ... and a day with nothing else has no second line
        self.assertEqual(three.count("Theme 3"), 1)  # not repeated as a highlight
        self.assertIn(f'id="stay-{self.hof.pk}"', html)  # the stay's card, on its check-in day

    def test_needs_attention_banner(self):
        html = self.page().content.decode()
        banner = re.search(r'<p class="callout-warning[^"]*" id="needs-attention">(.*?)</p>', html, re.S).group(1)
        self.assertIn(f'href="{reverse("trips:trip_todo", args=[self.trip.pk])}">1 to do</a>', banner)  # E2
        self.assertLess(html.index('id="needs-attention"'), html.index('class="day-nav"'))  # under the header
        BookingTask.objects.all().delete()
        Lodging.objects.all().delete()
        TransportLeg.objects.all().delete()
        TripActivity.objects.all().delete()  # a tour with no confirmation is "not booked"
        self.assertNotIn('id="needs-attention"', self.page().content.decode())

    def test_bookings_on_no_day_show_for_a_viewer(self):
        TransportLeg.objects.create(trip=self.trip, mode="train", origin="Ulm", destination="Bonn",
                                    date=date(2027, 9, 30))
        html = self.page(self.viewer).content.decode()
        block = html[html.index('id="not-on-any-day"'):html.index('id="day-1"')]
        self.assertIn("Journeys not on any day", block)
        self.assertIn("Ulm", block)
        self.assertIn("Stays outside the trip&#x27;s days", block.replace("'", "&#x27;"))
        self.assertIn("Early Inn", block)
        self.assertNotIn("a leg shows on the day it departs", block)  # the date hint is for editors
        self.assertIn("a leg shows on the day it departs", self.page(self.editor).content.decode())
        self.assertIn('href="#stray-legs">1 not on any day</a>', html)


class AboutThisTripTests(Fixture):
    def test_closed_fold_with_travellers_cities_goals_and_notes(self):
        from apps.trips.models import Traveler
        self.trip.notes = "Bring the rail passes."
        self.trip.save()
        self.trip.travelers.add(Traveler.objects.create(name="Regan"))
        html = self.page().content.decode()
        about = html[html.index('id="about"'):html.index("</details>", html.index('id="about"'))]
        self.assertIn('<details class="about-fold" id="about">', html)  # closed by default
        self.assertIn("About this trip", about)
        self.assertIn("Regan", about)
        self.assertIn("Bring the rail passes.", about)
        # The goals link moved to the Ideas shelf (P6), the fold after this one.
        goals = reverse("bucketlists:trip_goals", args=[self.trip.pk])
        self.assertNotIn(goals, about)
        shelf = html[html.index('id="ideas"'):html.index("</details>", html.index('id="ideas"'))]
        self.assertIn(goals, shelf)

    def test_open_when_the_trip_has_no_days(self):
        Day.objects.filter(trip=self.trip).delete()
        self.assertIn('<details class="about-fold" id="about" open>', self.page().content.decode())


class TidyLinkTests(Fixture):
    def test_in_the_menu_for_editors_only(self):
        tidy = reverse("trips:trip_tidy", args=[self.trip.pk])
        html = self.page(self.editor).content.decode()
        start = html.index("data-trip-menu")
        menu = html[start:html.index("</header>", start)]
        self.assertIn(f'href="{tidy}"', menu)
        self.assertNotIn(tidy, self.page(self.viewer).content.decode())


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
