"""Activities and events share one look: the banner header + Quick info / Actions
on detail pages, and the same card on list pages."""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event
from apps.locations.models import City, Country


class Fixture(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("u", "u@example.com", "pw-1234-abcd")
        country = Country.objects.create(
            name="Germany",
            slug="germany",
            iso_code="DE",
            iso3_code="DEU",
            continent="Europe",
            approval_status=ApprovalStatus.APPROVED,
        )
        city = City.objects.create(
            name="Munich",
            slug="munich",
            country=country,
            latitude=48,
            longitude=11,
            approval_status=ApprovalStatus.APPROVED,
        )
        festival = ActivityCategory.objects.get(name="Festival")
        self.activity = Activity.objects.create(
            category=festival,
            name="Oktoberfest",
            description="Beer",
            city=city,
            recurrence="yearly",
            usual_months=[9],
            created_by=user,
            visibility="public",
            approval_status=ApprovalStatus.APPROVED,
        )
        self.event = Event.objects.create(
            name="Oktoberfest 2027",
            category=festival,
            description="Beer",
            city=city,
            related_activity=self.activity,
            start_date=date.today() + timedelta(days=30),
            approval_status=ApprovalStatus.APPROVED,
            status="cancelled",
        )
        self.client.force_login(user)


class CatalogueStyleTests(Fixture):
    def test_detail_pages_share_the_layout(self):
        for url in (
            reverse("activities:activity_detail", args=[self.activity.slug]),
            reverse("events:event_detail", args=[self.event.slug]),
        ):
            with self.subTest(url=url):
                page = self.client.get(url)
                for text in ("Quick info", "Actions", "Munich, Germany", "Festival", "text-4xl font-bold md:text-5xl"):
                    self.assertContains(page, text)
        self.assertContains(self.client.get(reverse("events:event_detail", args=[self.event.slug])), "Cancelled")

    def test_list_pages_share_the_card(self):
        activities = self.client.get(reverse("activities:activity_list"))
        events = self.client.get(reverse("events:event_list"))
        for page, url in (
            (activities, reverse("activities:activity_detail", args=[self.activity.slug])),
            (events, reverse("events:event_detail", args=[self.event.slug])),
        ):
            self.assertContains(page, "sbl-card sbl-card-hover flex h-full flex-col overflow-hidden")
            self.assertContains(page, url)
        self.assertContains(activities, "Every year · September")
        self.assertNotContains(activities, "POIs")  # the old country-page leftovers are gone
        self.assertContains(events, "Cancelled")

    def test_activity_list_filters_by_country(self):
        url = reverse("activities:activity_list")
        self.assertContains(self.client.get(url, {"country": "germany"}), "Oktoberfest")
        self.assertNotContains(self.client.get(url, {"country": "france"}), "Oktoberfest")


class PlaceHeaderTests(Fixture):
    """Place pages wear the same banner (ux-consistency V4): no "Approved" badge, a summary strip, and for a city or
    a place Add to bucket list (the page's one filled button) and Add to a trip."""

    def setUp(self):
        super().setUp()
        from apps.locations.models import POI, Region

        self.country = Country.objects.get(slug="germany")
        self.city = City.objects.get(slug="munich")
        self.region = Region.objects.create(
            name="Bavaria", slug="bavaria", country=self.country, approval_status=ApprovalStatus.APPROVED
        )
        self.city.region = self.region
        self.city.population = 1500000
        self.city.save()
        self.poi = POI.objects.create(
            name="Englischer Garten",
            slug="englischer-garten",
            city=self.city,
            latitude=48.15,
            longitude=11.6,
            poi_type_id="park",
            approval_status=ApprovalStatus.APPROVED,
        )

    def pages(self):
        return {
            "country": reverse("locations:country_detail", args=["germany"]),
            "region": reverse("locations:region_detail", args=["bavaria"]),
            "city": reverse("locations:city_detail", args=["munich"]),
            "poi": reverse("locations:poi_detail", args=["englischer-garten"]),
        }

    def test_place_pages_use_the_banner_without_an_approved_badge(self):
        for kind, url in self.pages().items():
            with self.subTest(kind):
                html = self.client.get(url).content.decode()
                self.assertIn("data-detail-header", html)
                self.assertIn("text-4xl font-bold md:text-5xl", html)
                self.assertIn("data-header-summary", html)
                self.assertNotIn("data-detail-status", html)  # approved: no badge row
                self.assertNotIn(">Approved<", html.replace(" ", "").replace("\n", ""))
                self.assertNotIn("bg-sky-500", html)
                self.assertNotIn('style="height', html)
                self.assertNotIn("Statistics", html)

    def test_header_lines(self):
        pages = {kind: self.client.get(url).content.decode() for kind, url in self.pages().items()}
        self.assertIn("1 region", pages["country"])
        self.assertIn("1 city", pages["region"])
        self.assertIn("Bavaria, Germany", pages["city"])
        self.assertIn("Population 1,500,000", pages["city"])
        self.assertIn("Munich, Bavaria, Germany", pages["poi"])

    def test_city_and_place_carry_the_bucket_and_trip_buttons(self):
        for kind in ("city", "poi"):
            with self.subTest(kind):
                html = self.client.get(self.pages()[kind]).content.decode()
                strip = html.split("data-header-actions", 1)[1].split("</header>", 1)[0]
                self.assertIn("sbl-btn sbl-btn-primary", strip)
                self.assertIn("Add to bucket list", strip)
                self.assertIn("data-trip-add", strip)
                self.assertEqual(html.count("Add to bucket list"), 1)  # not repeated in the sidebar

    def test_a_pending_place_says_so(self):
        self.city.approval_status = ApprovalStatus.PENDING
        self.city.save()
        self.client.force_login(get_user_model().objects.create_user("s", "s@example.com", "pw", is_staff=True))
        html = self.client.get(self.pages()["city"]).content.decode()
        self.assertIn("data-detail-status", html)
        self.assertIn("until it's approved", html)
