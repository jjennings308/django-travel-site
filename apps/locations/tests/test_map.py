"""The Places map: a page with the list's filters, fed by a GeoJSON view of published places."""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import POI, City, Country

APPROVED = ApprovalStatus.APPROVED


class PlacesMapTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("u", "u@example.com", "pw-1234-abcd"))
        self.us = Country.objects.create(name="United States", slug="us", iso_code="US", iso3_code="USA",
                                         continent="North America", approval_status=APPROVED)
        self.ca = Country.objects.create(name="Canada", slug="ca", iso_code="CA", iso3_code="CAN",
                                         continent="North America", approval_status=APPROVED)
        self.moab = City.objects.create(name="Moab", slug="moab", country=self.us, latitude=38.57, longitude=-109.55,
                                        approval_status=APPROVED)
        self.mtl = City.objects.create(name="Montreal", slug="mtl", country=self.ca, latitude=45.5, longitude=-73.57,
                                       approval_status=APPROVED)
        self.arches = POI.objects.create(name="Arches <b>NP</b>", slug="arches", city=self.moab, latitude=38.73,
                                         longitude=-109.59, poi_type_id="nature", approval_status=APPROVED)
        POI.objects.create(name="Bell Centre", slug="bell", city=self.mtl, latitude=45.5, longitude=-73.57,
                           poi_type_id="sports", approval_status=APPROVED)
        POI.objects.create(name="Secret spot", slug="secret", city=self.moab, latitude=1, longitude=2,
                           approval_status=ApprovalStatus.PENDING)

    def data(self, query=""):
        return self.client.get(reverse("locations:poi_map_data") + query).json()

    def test_geojson_of_published_places(self):
        data = self.data()
        self.assertEqual(data["type"], "FeatureCollection")
        names = [f["properties"]["name"] for f in data["features"]]
        self.assertEqual(names, ["Arches <b>NP</b>", "Bell Centre"])  # pending left out; text as-is (the page escapes)
        arches = data["features"][0]
        self.assertEqual(arches["geometry"], {"type": "Point", "coordinates": [-109.59, 38.73]})
        self.assertEqual(arches["properties"]["subtitle"], "Nature Reserve · Moab, United States")
        self.assertEqual(arches["properties"]["url"], reverse("locations:poi_detail", args=["arches"]))

    def test_filters_match_the_list(self):
        self.assertEqual([f["properties"]["name"] for f in self.data(f"?country={self.ca.pk}")["features"]], ["Bell Centre"])
        self.assertEqual([f["properties"]["name"] for f in self.data("?type=nature")["features"]], ["Arches <b>NP</b>"])
        self.assertEqual([f["properties"]["name"] for f in self.data("?q=bell")["features"]], ["Bell Centre"])

    def test_one_query_however_many_places(self):
        with CaptureQueriesContext(connection) as before:
            self.data()
        for i in range(5):
            POI.objects.create(name=f"P{i}", slug=f"p{i}", city=self.moab, latitude=1, longitude=2, approval_status=APPROVED)
        with CaptureQueriesContext(connection) as after:
            self.data()
        self.assertEqual(len(before), len(after))

    def test_page_carries_the_map_and_keeps_filters(self):
        page = self.client.get(reverse("locations:poi_map") + f"?country={self.us.pk}")
        self.assertContains(page, "data-sbl-map")
        self.assertContains(page, reverse("locations:poi_map_data") + f"?country={self.us.pk}")
        self.assertContains(page, 'data-provider="osm"')
        self.assertContains(page, "leaflet/1.9.4/leaflet.js")
        self.assertContains(page, reverse("locations:poi_list") + f"?country={self.us.pk}")  # List/Map switch
        self.assertContains(self.client.get(reverse("locations:poi_list")), reverse("locations:poi_map"))

    @override_settings(MAP_PROVIDER="google")
    def test_provider_comes_from_settings(self):
        page = self.client.get(reverse("locations:poi_map"))
        self.assertContains(page, 'data-provider="google"')
        self.assertNotContains(page, "leaflet.js")  # no adapter yet: the page says the map isn't available

    def test_open_to_visitors(self):
        # Public since site roadmap R22; the data is published places only.
        self.client.logout()
        self.assertEqual(self.client.get(reverse("locations:poi_map")).status_code, 200)
        self.assertEqual(self.client.get(reverse("locations:poi_map_data")).status_code, 200)


class TileRefererTests(TestCase):
    def test_tiles_send_the_site_origin(self):
        """OpenStreetMap blocks tile requests without a Referer; the site's own policy is
        "same-origin", so the tile layer must ask for the origin to be sent."""
        from django.contrib.staticfiles import finders
        with open(finders.find("core/map.js"), encoding="utf-8") as f:
            self.assertIn('referrerPolicy: "strict-origin-when-cross-origin"', f.read())
