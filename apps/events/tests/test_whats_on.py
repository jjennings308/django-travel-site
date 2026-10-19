"""What's on (site roadmap R21): the month calendar, What's on / Things to do on place pages, and
"Add to my calendar"."""
from datetime import date, time
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.events import whats_on
from apps.events.models import Event
from apps.locations.models import POI, City, Country, Region

User = get_user_model()
APPROVED = {"approval_status": ApprovalStatus.APPROVED}
TODAY = date(2027, 4, 20)
from django.utils.timezone import localdate as REAL_LOCALDATE  # noqa: E402


def pin_today(day=TODAY):
    return mock.patch("django.utils.timezone.localdate", return_value=day)


class Fixture(TestCase):
    def setUp(self):
        patcher = pin_today()
        patcher.start()
        self.addCleanup(patcher.stop)
        self.de = Country.objects.create(name="Germany", slug="germany", iso_code="DE", iso3_code="DEU",
                                         continent="Europe", **APPROVED)
        self.bavaria = Region.objects.create(name="Bavaria", slug="bavaria", country=self.de, **APPROVED)
        self.munich = City.objects.create(name="Munich", slug="munich", country=self.de, region=self.bavaria,
                                          latitude=48.137, longitude=11.575, **APPROVED)
        self.freising = City.objects.create(name="Freising", slug="freising", country=self.de, region=self.bavaria,
                                            latitude=48.403, longitude=11.749, **APPROVED)  # ~32 km
        self.nuremberg = City.objects.create(name="Nuremberg", slug="nuremberg", country=self.de,
                                             region=self.bavaria, latitude=49.452, longitude=11.077,
                                             **APPROVED)  # ~150 km
        self.arena = POI.objects.create(name="Allianz Arena", slug="allianz-arena", city=self.munich,
                                        latitude=48.219, longitude=11.625, **APPROVED)
        self.cat, _ = ActivityCategory.objects.get_or_create(slug="festival", defaults={"name": "Festival"})
        self.member = User.objects.create_user("mem", "mem@example.com", "pw-1234-abcd")

    def event(self, name, start, end=None, city=None, **extra):
        defaults = {"category": self.cat, **APPROVED}
        defaults.update(extra)
        return Event.objects.create(name=name, slug=name.lower().replace(" ", "-"), start_date=start, end_date=end,
                                    city=city or self.munich, **defaults)


class MonthTests(Fixture):
    def test_events_on_every_day_they_run_across_month_edges(self):
        spring = self.event("Spring fair", date(2027, 4, 30), date(2027, 5, 2))
        new_year = self.event("New Year run", date(2027, 12, 31), date(2028, 1, 1))
        april = whats_on.month_events(Event.objects.all(), 2027, 4)
        may = whats_on.month_events(Event.objects.all(), 2027, 5)
        self.assertIn(spring, april)
        self.assertIn(spring, may)
        grid = {d.date: d for week in whats_on.month_grid(may, 2027, 5) for d in week}
        self.assertEqual([e.name for e in grid[date(2027, 5, 2)].events], ["Spring fair"])
        self.assertEqual(grid[date(2027, 5, 3)].events, [])
        self.assertIn(new_year, whats_on.month_events(Event.objects.all(), 2028, 1))
        self.assertEqual(whats_on.neighbours(2027, 12), ((2027, 11), (2028, 1)))
        self.assertEqual(whats_on.neighbours(2027, 1), ((2026, 12), (2027, 2)))

    def test_day_cap(self):
        for n in range(5):
            self.event(f"Gig {n}", date(2027, 4, 22))
        grid = {d.date: d for week in whats_on.month_grid(
            whats_on.month_events(Event.objects.all(), 2027, 4), 2027, 4) for d in week}
        day = grid[date(2027, 4, 22)]
        self.assertEqual((len(day.shown), day.more), (3, 2))

    def test_page_today_pending_filters_and_queries(self):
        self.event("Public gig", date(2027, 4, 22))
        self.event("Pending gig", date(2027, 4, 23), approval_status=ApprovalStatus.PENDING, created_by=self.member)
        response = self.client.get(reverse("events:calendar_today"))
        self.assertRedirects(response, reverse("events:calendar", args=[2027, 4]), fetch_redirect_response=False)
        page = self.client.get(reverse("events:calendar", args=[2027, 4]))
        self.assertContains(page, "Public gig")
        self.assertNotContains(page, "Pending gig")
        self.client.force_login(self.member)
        self.assertContains(self.client.get(reverse("events:calendar", args=[2027, 4])), "Pending gig")
        other = Country.objects.create(name="France", slug="france", iso_code="FR", iso3_code="FRA",
                                       continent="Europe", **APPROVED)
        filtered = self.client.get(reverse("events:calendar", args=[2027, 4]), {"country": "france"})
        self.assertNotContains(filtered, "Public gig")
        self.assertEqual(self.client.get(reverse("events:calendar", args=[2027, 13])).status_code, 404)

        def count():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(reverse("events:calendar", args=[2027, 4]))
            return len(ctx.captured_queries)
        before = count()
        for n in range(4):
            self.event(f"Extra {n}", date(2027, 4, 10 + n), city=self.freising)
        self.assertEqual(count(), before)
        del other

    def test_today_follows_the_readers_zone(self):
        # 23:30 UTC is already tomorrow in Tokyo: on the last day of a month a reader there lands on the
        # next month. "Now" stays today (a far-off now would expire the login session).
        from datetime import datetime, timedelta, timezone as dt_timezone
        from apps.accounts.models import AccountSettings
        AccountSettings.objects.update_or_create(user=self.member, defaults={"timezone": "Asia/Tokyo"})
        self.client.force_login(self.member)
        utc_today = datetime.now(dt_timezone.utc).date()
        now = datetime.combine(utc_today, time(23, 30), tzinfo=dt_timezone.utc)
        tokyo = utc_today + timedelta(days=1)
        with mock.patch("django.utils.timezone.localdate", new=REAL_LOCALDATE), \
                mock.patch("django.utils.timezone.now", return_value=now):
            response = self.client.get(reverse("events:calendar_today"))
            self.assertEqual(response["Location"], reverse("events:calendar", args=[tokyo.year, tokyo.month]))
            self.client.logout()
            response = self.client.get(reverse("events:calendar_today"))  # a signed-out reader: UTC
            self.assertEqual(response["Location"], reverse("events:calendar", args=[utc_today.year, utc_today.month]))


class WhatsOnTests(Fixture):
    def fragment(self, kind, slug):
        return self.client.get(reverse("events:whats_on", args=[kind, slug]))

    def test_city_then_nearby_within_50_km(self):
        self.event("Munich gig", date(2027, 5, 1))
        self.event("Freising fair", date(2027, 4, 25), city=self.freising)
        self.event("Nuremberg fest", date(2027, 4, 26), city=self.nuremberg)
        self.event("Past gig", date(2027, 3, 1))
        found = whats_on.events_for("city", self.munich, Event.objects.all())
        self.assertEqual([e.name for e in found], ["Munich gig", "Freising fair"])
        self.assertEqual(found[1].distance_km, 32)
        page = self.fragment("city", "munich")
        self.assertContains(page, "Nearby, 32 km")
        self.assertNotContains(page, "Nuremberg fest")

    def test_region_country_and_venue_and_things_to_do(self):
        self.event("Nuremberg fest", date(2027, 4, 26), city=self.nuremberg)
        self.event("Home game", date(2027, 5, 2), poi=self.arena)
        Activity.objects.create(name="Stadium tour", slug="stadium-tour", category=self.cat, description="x",
                                venue=self.arena, visibility="public", **APPROVED)
        Activity.objects.create(name="Secret tour", slug="secret-tour", category=self.cat, description="x",
                                venue=self.arena, visibility="private", **APPROVED)
        self.assertContains(self.fragment("region", "bavaria"), "Nuremberg fest")
        self.assertContains(self.fragment("country", "germany"), "Nuremberg fest")
        venue = self.fragment("place", "allianz-arena")
        self.assertContains(venue, "Home game")
        self.assertNotContains(venue, "Nuremberg fest")
        self.assertContains(venue, "Stadium tour")
        self.assertNotContains(venue, "Secret tour")
        self.assertEqual(self.fragment("planet", "earth").status_code, 404)

    def test_pending_hidden_and_empty_and_fixed_queries(self):
        self.assertEqual(self.fragment("city", "freising").content.strip(), b"")
        self.event("Pending gig", date(2027, 5, 1), approval_status=ApprovalStatus.PENDING, created_by=self.member)
        self.assertNotContains(self.fragment("city", "munich"), "Pending gig")

        def count():
            with CaptureQueriesContext(connection) as ctx:
                self.fragment("city", "munich")
            return len(ctx.captured_queries)
        before = count()
        for n in range(4):
            self.event(f"Gig {n}", date(2027, 5, 3 + n))
            Activity.objects.create(name=f"Walk {n}", slug=f"walk-{n}", category=self.cat, description="x",
                                    city=self.munich, visibility="public", **APPROVED)
        self.assertEqual(count(), before)

    def test_place_pages_include_the_card(self):
        self.client.force_login(self.member)
        page = self.client.get(reverse("locations:city_detail", args=["munich"]))
        self.assertContains(page, reverse("events:whats_on", args=["city", "munich"]))
        self.assertContains(self.client.get(reverse("locations:poi_detail", args=["allianz-arena"])),
                            reverse("events:whats_on", args=["place", "allianz-arena"]))


class IcsTests(Fixture):
    def test_timed_event_in_its_own_zone(self):
        gig = self.event("Night gig", date(2027, 5, 1), start_time=time(20, 0), end_time=time(23, 0),
                         timezone="Europe/Berlin")
        body = self.client.get(reverse("events:event_ics", args=[gig.slug])).content.decode()
        self.assertIn("DTSTART;TZID=Europe/Berlin:20270501T200000", body)
        self.assertIn("DTEND;TZID=Europe/Berlin:20270501T230000", body)
        self.assertIn(f"UID:event-{gig.pk}@sharebucketlist.com", body)

    def test_all_day_end_is_exclusive_and_hidden_is_404(self):
        fair = self.event("Spring fair", date(2027, 4, 30), date(2027, 5, 2))
        response = self.client.get(reverse("events:event_ics", args=[fair.slug]))
        self.assertEqual(response["Content-Type"], "text/calendar; charset=utf-8")
        body = response.content.decode()
        self.assertIn("DTSTART;VALUE=DATE:20270430", body)
        self.assertIn("DTEND;VALUE=DATE:20270503", body)
        pending = self.event("Pending gig", date(2027, 5, 1), approval_status=ApprovalStatus.PENDING,
                             created_by=self.member)
        self.assertEqual(self.client.get(reverse("events:event_ics", args=[pending.slug])).status_code, 404)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("events:event_ics", args=[pending.slug])).status_code, 200)
        self.assertContains(self.client.get(reverse("events:event_detail", args=[fair.slug])),
                            reverse("events:event_ics", args=[fair.slug]))
