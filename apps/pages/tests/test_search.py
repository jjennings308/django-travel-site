"""Catalogue search (site roadmap R20)."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event
from apps.locations.models import POI, City, Country, Region
from apps.pages import search

User = get_user_model()
APPROVED = {"approval_status": ApprovalStatus.APPROVED}


class Fixture(TestCase):
    def setUp(self):
        self.de = Country.objects.create(name="Germany", slug="germany", iso_code="DE", iso3_code="DEU",
                                         continent="Europe", **APPROVED)
        self.jp = Country.objects.create(name="Japan", slug="japan", iso_code="JP", iso3_code="JPN",
                                         continent="Asia", **APPROVED)
        self.bavaria = Region.objects.create(name="Bavaria", slug="bavaria", country=self.de, **APPROVED)
        self.munich = City.objects.create(name="München", slug="muenchen", country=self.de, region=self.bavaria,
                                          latitude=48.1, longitude=11.6, description="Beer halls and museums.",
                                          **APPROVED)
        self.kyoto = City.objects.create(name="Kyoto", slug="kyoto", country=self.jp, latitude=35, longitude=135.7,
                                         **APPROVED)
        self.castle = POI.objects.create(name="Neuschwanstein Castle", slug="neuschwanstein", city=self.munich,
                                         latitude=47.5, longitude=10.7, poi_type_id="landmark", **APPROVED)
        self.museum = POI.objects.create(name="Deutsches Museum", slug="deutsches-museum", city=self.munich,
                                         latitude=48.1, longitude=11.5, poi_type_id="museum", **APPROVED)
        self.hidden_place = POI.objects.create(name="Secret Castle Bar", slug="secret", city=self.munich,
                                               latitude=48.1, longitude=11.5)  # pending
        self.festivals = ActivityCategory.objects.get_or_create(slug="festival", defaults={"name": "Festival"})[0]
        self.tours = ActivityCategory.objects.get_or_create(slug="tours", defaults={"name": "Tours"})[0]
        self.okto = Activity.objects.create(name="Oktoberfest", slug="oktoberfest", category=self.festivals,
                                            description="The world's biggest beer festival.", city=self.munich,
                                            visibility="public", usual_months=[9, 10], **APPROVED)
        self.walk = Activity.objects.create(name="Castle walk", slug="castle-walk", category=self.tours,
                                            description="A walk past the old town to the castle.",
                                            city=self.kyoto, visibility="public", usual_months=[4], **APPROVED)
        self.private = Activity.objects.create(name="Castle picnic", slug="castle-picnic", category=self.tours,
                                               description="x", visibility="private", **APPROVED)
        today = timezone.localdate()
        self.next_okto = Event.objects.create(name="Oktoberfest 2027", slug="okto-2027", city=self.munich,
                                              related_activity=self.okto, category=self.festivals,
                                              start_date=today + timedelta(days=60),
                                              end_date=today + timedelta(days=75), **APPROVED)
        self.last_okto = Event.objects.create(name="Oktoberfest 2025", slug="okto-2025", city=self.munich,
                                              related_activity=self.okto, category=self.festivals,
                                              start_date=today - timedelta(days=300),
                                              end_date=today - timedelta(days=285), **APPROVED)
        self.member = User.objects.create_user("mem", "mem@example.com", "pw-1234-abcd")
        self.pending_event = Event.objects.create(name="Castle concert", slug="castle-concert", city=self.munich,
                                                  start_date=today + timedelta(days=10), created_by=self.member,
                                                  category=self.tours)

    def found(self, q, user=None, **filters):
        from django.contrib.auth.models import AnonymousUser
        groups = search.grouped(q, user or AnonymousUser(), search.Filters(**filters))
        return {g.kind: [obj.name for obj in g.items] for g in groups}

    def page(self, **params):
        return self.client.get(reverse("pages:search"), params)


class RankingTests(Fixture):
    def test_name_beats_place_beats_description(self):
        found = self.found("castle")
        self.assertEqual(found["place"][0], "Neuschwanstein Castle")
        self.assertEqual(found["activity"], ["Castle walk"])  # name match; private picnic never
        self.assertIn("Oktoberfest", self.found("munchen")["activity"])  # by its place
        self.assertIn("München", self.found("museums")["city"])  # by its description, after names

    def test_exact_name_first_and_areas(self):
        found = self.found("bavaria")
        self.assertEqual(found["area"], ["Bavaria"])
        self.assertEqual(self.found("japan")["area"][0], "Japan")
        oktoberfest = search.grouped("oktoberfest", None, search.Filters())
        activity = next(g for g in oktoberfest if g.kind == "activity")
        self.assertEqual(activity.items[0].name, "Oktoberfest")

    def test_typos_and_accents(self):
        self.assertIn("Neuschwanstein Castle", self.found("Neuschwanstien")["place"])
        self.assertIn("München", self.found("Munchen")["city"])
        self.assertIn("München", self.found("MÜNCHEN")["city"])
        self.assertNotIn("area", self.found("japon kyto zzz"))


class FilterTests(Fixture):
    def test_upcoming_events_unless_past(self):
        self.assertEqual(self.found("oktoberfest")["event"], ["Oktoberfest 2027"])
        self.assertEqual(sorted(self.found("oktoberfest", past=True)["event"]),
                         ["Oktoberfest 2025", "Oktoberfest 2027"])

    def test_country_month_category_kind(self):
        self.assertEqual(self.found("castle", country="japan"), {"activity": ["Castle walk"]})
        by_month = self.found("castle", month=4)
        self.assertEqual(set(by_month), {"activity"})  # places dropped: month is for activities/events
        self.assertEqual(self.found("oktoberfest", month=9, past=True).get("activity"), ["Oktoberfest"])
        self.assertNotIn("activity", self.found("castle", category="festival"))
        self.assertEqual(set(self.found("castle", kind="place")), {"place"})

    def test_unpublished_never_found(self):
        everything = [name for names in self.found("castle").values() for name in names]
        for hidden in ("Secret Castle Bar", "Castle picnic", "Castle concert"):
            self.assertNotIn(hidden, everything)
        other = User.objects.create_user("oth", "oth@example.com", "pw-1234-abcd")
        self.assertNotIn("Castle concert", self.found("castle", user=other).get("event", []))
        self.assertIn("Castle concert", self.found("castle", user=self.member)["event"])  # their own


class PageTests(Fixture):
    def test_signed_out_search_and_header_box(self):
        response = self.page(q="castle")
        self.assertContains(response, "Neuschwanstein Castle")
        self.assertContains(response, reverse("locations:poi_detail", args=["neuschwanstein"]))
        self.assertContains(response, 'id="site-search"')
        self.assertContains(self.client.get(reverse("pages:about")), 'id="site-search"')  # public shell
        self.assertContains(self.page(), "Type at least two letters")
        self.assertContains(self.page(q="zzzzqqq"), "Nothing matches")

    def test_one_kind_is_paginated_and_area_rows(self):
        response = self.page(q="castle", kind="place")
        self.assertContains(response, "Neuschwanstein Castle")
        self.assertContains(response, "All results")
        area = self.page(q="bavaria", kind="area")
        self.assertContains(area, reverse("locations:region_detail", args=["bavaria"]))

    def test_query_count_is_fixed(self):
        def count(q):
            with CaptureQueriesContext(connection) as ctx:
                self.page(q=q)
            return len(ctx.captured_queries)
        before = count("castle")
        for n in range(6):
            POI.objects.create(name=f"Castle {n}", slug=f"castle-{n}", city=self.kyoto, latitude=1, longitude=1,
                               **APPROVED)
            Activity.objects.create(name=f"Castle tour {n}", slug=f"castle-tour-{n}", category=self.tours,
                                    description="x", city=self.kyoto, visibility="public", **APPROVED)
        self.assertEqual(count("castle"), before)

    @override_settings(RATELIMIT_ENABLED=True)
    def test_rate_limited(self):
        from django.core.cache import caches
        caches["default"].clear()
        from unittest import mock
        with mock.patch("apps.core.ratelimit.hit", return_value=(False, 30)):
            self.assertEqual(self.page(q="castle").status_code, 429)
