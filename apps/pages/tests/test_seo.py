"""SEO basics (site roadmap R22): public place pages, robots.txt, sitemap.xml, page tags and JSON-LD."""
import json
import re
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event
from apps.locations.models import POI, City, Country, Region

User = get_user_model()
APPROVED = {"approval_status": ApprovalStatus.APPROVED}
PENDING = {"approval_status": ApprovalStatus.PENDING}


def jsonld(response):
    found = re.findall(r'<script type="application/ld\+json">(.*?)</script>', response.content.decode(), re.S)
    return [json.loads(block) for block in found]


class Fixture(TestCase):
    def setUp(self):
        self.member = User.objects.create_user("mem", "mem@example.com", "pw-1234-abcd")
        self.de = Country.objects.create(name="Germany", slug="germany", iso_code="DE", iso3_code="DEU",
                                         continent="Europe", **APPROVED)
        self.bavaria = Region.objects.create(name="Bavaria", slug="bavaria", country=self.de, **APPROVED)
        self.munich = City.objects.create(name="Munich", slug="munich", country=self.de, region=self.bavaria,
                                          latitude=48.137, longitude=11.575, description="Beer & <b>art</b>.",
                                          **APPROVED)
        self.castle = POI.objects.create(name="Nymphenburg Palace", slug="nymphenburg", city=self.munich,
                                         latitude=48.158, longitude=11.503, address="Schloß Nymphenburg 1",
                                         **APPROVED)
        self.pending_place = POI.objects.create(name="Secret Bar", slug="secret-bar", city=self.munich,
                                                latitude=48.1, longitude=11.5, submitted_by=self.member, **PENDING)
        self.pending_city = City.objects.create(name="Hiddenville", slug="hiddenville", country=self.de,
                                                latitude=48, longitude=11, **PENDING)
        self.cat, _ = ActivityCategory.objects.get_or_create(slug="festival", defaults={"name": "Festival"})
        self.okto = Activity.objects.create(name="Oktoberfest", slug="oktoberfest", category=self.cat,
                                            description="The </script> beer festival.", city=self.munich,
                                            visibility="public", **APPROVED)
        today = timezone.localdate()
        self.event = Event.objects.create(name="Opera night", slug="opera-night", category=self.cat,
                                          city=self.munich, start_date=today + timedelta(days=30),
                                          start_time=time(19, 30), end_time=time(22, 0),
                                          timezone="Europe/Berlin", **APPROVED)
        self.old_event = Event.objects.create(name="Old fair", slug="old-fair", category=self.cat, city=self.munich,
                                              start_date=today - timedelta(days=500), **APPROVED)
        self.pending_event = Event.objects.create(name="Pending gig", slug="pending-gig", category=self.cat,
                                                  city=self.munich, start_date=today + timedelta(days=5),
                                                  created_by=self.member)


class PublicPlacePagesTests(Fixture):
    def test_signed_out_visitors_see_approved_places_only(self):
        for name, args in (("locations:country_list", []), ("locations:region_list", []), ("locations:city_list", []),
                           ("locations:poi_list", []), ("locations:poi_map", []), ("locations:country_detail", ["germany"]),
                           ("locations:region_detail", ["bavaria"]), ("locations:city_detail", ["munich"]),
                           ("locations:poi_detail", ["nymphenburg"])):
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200, name)
        self.assertEqual(self.client.get(reverse("locations:poi_detail", args=["secret-bar"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("locations:city_detail", args=["hiddenville"])).status_code, 404)
        places = self.client.get(reverse("locations:poi_list"), {"status": "pending"})
        self.assertContains(places, "Nymphenburg Palace")
        self.assertNotContains(places, "Secret Bar")  # the status filter is staff-only
        self.assertNotContains(places, 'name="status"')
        self.assertEqual(self.client.get(reverse("locations:poi_add")).status_code, 302)  # adding still needs a login

    def test_submitter_and_staff_see_pending(self):
        other = User.objects.create_user("oth", "oth@example.com", "pw-1234-abcd")
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("locations:poi_detail", args=["secret-bar"])).status_code, 404)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("locations:poi_detail", args=["secret-bar"])).status_code, 200)
        staff = User.objects.create_superuser("root", "root@example.com", "pw-1234-abcd")
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("locations:city_detail", args=["hiddenville"])).status_code, 200)
        self.assertContains(self.client.get(reverse("locations:poi_list")), 'name="status"')


class RobotsSitemapTests(Fixture):
    def test_robots_disallows_private_areas_and_names_the_sitemap(self):
        body = self.client.get("/robots.txt").content.decode()
        for path in ("/trips/", "/public/", "/accounts/", "/staff/", "/admin/", "/bucketlists/", "/search/"):
            self.assertIn(f"Disallow: {path}", body)
        self.assertIn("Sitemap: http://127.0.0.1:8000/sitemap.xml", body)
        with override_settings(STAGING=True):
            self.assertEqual(self.client.get("/robots.txt").content.decode(), "User-agent: *\nDisallow: /\n")

    def test_sitemap_lists_published_items_only(self):
        body = self.client.get("/sitemap.xml").content.decode()
        for path in ("/locations/pois/nymphenburg/", "/locations/cities/munich/", "/locations/countries/germany/",
                     "/locations/regions/bavaria/", "/activities/oktoberfest/", "/events/opera-night/",
                     "/help/", "/about/"):
            self.assertIn(f"<loc>http://127.0.0.1:8000{path}</loc>", body)
        for hidden in ("secret-bar", "hiddenville", "pending-gig", "old-fair", "/bucketlists/", "/trips/"):
            self.assertNotIn(hidden, body)
        self.assertIn("/help/getting-started/", body)
        self.assertNotIn("/help/running-the-site/", body)  # a staff guide


class TagTests(Fixture):
    def test_every_page_has_description_canonical_and_preview_tags(self):
        page = self.client.get(reverse("locations:city_detail", args=["munich"]), {"page": 2})
        self.assertContains(page, '<link rel="canonical" href="http://127.0.0.1:8000/locations/cities/munich/">')
        self.assertContains(page, '<meta property="og:title" content="Munich, Bavaria, Germany">')
        self.assertContains(page, '<meta name="description" content="Beer &amp; art.">')
        self.assertContains(page, 'og:image" content="http://127.0.0.1:8000/static/core/branding/png/sbl-logo-hero')
        self.assertContains(self.client.get(reverse("pages:about")), 'name="twitter:card" content="summary_large_image"')

    def test_noindex_on_search_public_lists_and_shared_trips(self):
        self.assertContains(self.client.get(reverse("pages:search"), {"q": "munich"}), 'name="robots" content="noindex"')
        self.assertNotContains(self.client.get(reverse("pages:about")), 'content="noindex"')
        User.objects.filter(pk=self.member.pk).update(profile_visibility="public")
        self.assertContains(self.client.get(reverse("bucketlists:public_list", args=["mem"])),
                            'name="robots" content="noindex"')
        from apps.trips.models import Trip
        trip = Trip.objects.create(name="Shared", start_date=date(2027, 5, 1), end_date=date(2027, 5, 2))
        trip.enable_public()
        self.assertContains(self.client.get(reverse("public_trip", args=[trip.public_token])),
                            'name="robots" content="noindex"')


class JsonLdTests(Fixture):
    def test_event(self):
        data = jsonld(self.client.get(reverse("events:event_detail", args=["opera-night"])))[0]
        self.assertEqual(data["@type"], "Event")
        self.assertEqual(data["name"], "Opera night")
        self.assertRegex(data["startDate"], r"^\d{4}-\d\d-\d\dT19:30:00\+0[12]:00$")  # local time, Berlin offset
        self.assertEqual(data["location"]["address"]["addressCountry"], "DE")
        self.assertEqual(data["location"]["geo"]["latitude"], 48.137)
        self.assertEqual(data["eventStatus"], "https://schema.org/EventScheduled")
        self.assertEqual(data["url"], "http://127.0.0.1:8000/events/opera-night/")

    def test_place_city_activity_and_escaping(self):
        place = jsonld(self.client.get(reverse("locations:poi_detail", args=["nymphenburg"])))[0]
        self.assertEqual((place["@type"], place["address"]["streetAddress"]), ("TouristAttraction", "Schloß Nymphenburg 1"))
        city = jsonld(self.client.get(reverse("locations:city_detail", args=["munich"])))[0]
        self.assertEqual((city["@type"], city["containedInPlace"]["name"]), ("City", "Germany"))
        self.assertEqual(jsonld(self.client.get(reverse("activities:activity_detail", args=["oktoberfest"])))[0]["@type"],
                         "TouristTrip")
        Activity.objects.create(name="Rock </script><b>& roll", slug="rock", category=self.cat, description="x",
                                visibility="public", **APPROVED)
        response = self.client.get(reverse("activities:activity_detail", args=["rock"]))
        self.assertEqual(jsonld(response)[0]["name"], "Rock </script><b>& roll")  # parsed back intact...
        self.assertIn("Rock \\u003C/script\\u003E\\u003Cb\\u003E\\u0026 roll", response.content.decode())  # ...escaped
