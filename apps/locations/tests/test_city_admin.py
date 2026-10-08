"""City admin: the Region select is limited to the chosen country."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.admin import CityAdminForm
from apps.locations.models import City, Country, Region


class CityAdminRegionTests(TestCase):
    def setUp(self):
        self.austria = Country.objects.create(name="Austria", slug="austria", iso_code="AT", iso3_code="AUT", continent="Europe")
        self.italy = Country.objects.create(name="Italy", slug="italy", iso_code="IT", iso3_code="ITA", continent="Europe")
        self.tyrol = Region.objects.create(country=self.austria, name="Tyrol", slug="tyrol")
        self.tuscany = Region.objects.create(country=self.italy, name="Tuscany", slug="tuscany")
        self.city = City.objects.create(name="Innsbruck", slug="innsbruck", country=self.austria, region=self.tyrol,
                                        latitude=47, longitude=11, approval_status=ApprovalStatus.APPROVED)

    def form(self, region):
        data = {f: getattr(self.city, f) for f in ("name", "slug", "latitude", "longitude", "visitor_count",
                                                     "average_rating", "review_count", "featured_order")}
        data.update(country=self.austria.pk, region=region.pk)
        return CityAdminForm(data, instance=self.city)

    def test_region_must_be_in_the_country(self):
        form = self.form(self.tuscany)
        form.is_valid()
        self.assertIn("Tuscany is not in Austria.", form.errors.get("region", []))
        form = self.form(self.tyrol)
        form.is_valid()
        self.assertNotIn("region", form.errors)

    def test_change_page_tags_regions_with_their_country(self):
        admin = get_user_model().objects.create_superuser("root", "root@example.com", "pw-1234-abcd")
        self.client.force_login(admin)
        page = self.client.get(reverse("admin:locations_city_change", args=[self.city.pk]))
        self.assertContains(page, f'data-country="{self.italy.pk}"')
        self.assertContains(page, "locations/admin/region_by_country.js")
