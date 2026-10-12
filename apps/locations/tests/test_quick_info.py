"""The Quick Info box on city and POI pages names the region and links to it."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import POI, City, Country, Region


class QuickInfoRegionTests(TestCase):
    def setUp(self):
        country = Country.objects.create(name="Testland", slug="testland", iso_code="TL", iso3_code="TLD", continent="Europe")
        self.region = Region.objects.create(country=country, name="High Valley", slug="high-valley")
        self.city = City.objects.create(name="Testville", slug="testville", country=country, region=self.region,
                                        latitude=1, longitude=2, approval_status=ApprovalStatus.APPROVED)
        self.poi = POI.objects.create(name="Old Bridge", slug="old-bridge", city=self.city, latitude=1, longitude=2,
                                      approval_status=ApprovalStatus.APPROVED)
        self.client.force_login(get_user_model().objects.create_user("u", "u@example.com", "pw-1234-abcd"))

    def test_city_and_poi_pages_link_the_region(self):
        region_url = reverse("locations:region_detail", args=[self.region.slug])
        for url in (reverse("locations:city_detail", args=[self.city.slug]),
                    reverse("locations:poi_detail", args=[self.poi.slug])):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, region_url)
                self.assertContains(response, "High Valley")


class CityListRegionFilterTests(TestCase):
    """The cities list filters by region, with region options tagged by country."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        self.client.force_login(get_user_model().objects.create_user("u", "u@example.com", "pw-1234-abcd"))
        self.us = Country.objects.create(name="United States", slug="us", iso_code="US", iso3_code="USA",
                                         continent="North America", approval_status=ApprovalStatus.APPROVED)
        self.mo = Region.objects.create(country=self.us, name="Missouri", code="MO", slug="missouri")
        self.ks = Region.objects.create(country=self.us, name="Kansas", code="KS", slug="kansas")
        for region, slug in ((self.mo, "kansas-city-mo-us"), (self.ks, "kansas-city-ks-us")):
            City.objects.create(name="Kansas City", slug=slug, country=self.us, region=region, latitude=39,
                                longitude=-94, approval_status=ApprovalStatus.APPROVED)

    def test_region_filter_and_field_order(self):
        url = reverse("locations:city_list")
        page = self.client.get(url, {"country": self.us.pk, "region": self.ks.pk})
        self.assertContains(page, "kansas-city-ks-us")
        self.assertNotContains(page, "kansas-city-mo-us")
        html = page.content.decode()
        self.assertIn(f'value="{self.ks.pk}" data-country="{self.us.pk}" selected', html)
        self.assertIn("locations/country_filter.js", html)
        order = [html.index(f'id="filter_{n}"') for n in ("q", "country", "region", "status")]
        self.assertEqual(order, sorted(order))
