"""Place (POI) types are a table managed in the admin, keyed by a fixed code."""
from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.forms import POIForm
from apps.locations.models import POI, City, Country, PlaceType

APPROVED = ApprovalStatus.APPROVED


class PlaceTypeTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_superuser("boss", "boss@example.com", "pw-1234-abcd")
        self.client.force_login(self.staff)
        country = Country.objects.create(name="Testland", slug="testland", iso_code="TL", iso3_code="TLD",
                                         continent="Europe", approval_status=APPROVED)
        self.city = City.objects.create(name="Testville", slug="testville", country=country, latitude=1, longitude=2,
                                        approval_status=APPROVED)
        self.poi = POI.objects.create(name="Old Bridge", slug="old-bridge", city=self.city, latitude=1, longitude=2,
                                      poi_type_id="historical", approval_status=APPROVED)

    def test_seeded_with_the_old_list(self):
        self.assertEqual(PlaceType.objects.count(), 14)
        self.assertEqual(PlaceType.objects.get(code="sports").name, "Sports Venues")
        self.assertEqual(POI.objects.create(name="X", slug="x", city=self.city, latitude=1, longitude=2).poi_type_id, "landmark")

    def test_added_in_admin_and_offered(self):
        self.client.post(reverse("admin:locations_placetype_add"),
                         {"name": "Waterfall", "code": "waterfall", "icon": "", "sort_order": 5, "is_active": "on"})
        self.assertTrue(PlaceType.objects.filter(code="waterfall", name="Waterfall").exists())
        self.assertIn("waterfall", [c for c, _ in PlaceType.choices()])
        self.assertIn(PlaceType.objects.get(code="waterfall"), POIForm(instance=self.poi).fields["poi_type"].queryset)
        self.assertContains(self.client.get(reverse("locations:poi_list")), 'value="waterfall"')

    def test_code_is_fixed_once_saved(self):
        page = self.client.get(reverse("admin:locations_placetype_change", args=[PlaceType.objects.get(code="museum").pk]))
        self.assertNotContains(page, 'name="code"')

    def test_retired_type_kept_by_its_places(self):
        PlaceType.objects.filter(code="historical").update(is_active=False)
        self.assertNotIn("historical", [c for c, _ in PlaceType.choices()])
        self.assertIn(PlaceType.objects.get(code="historical"), POIForm(instance=self.poi).fields["poi_type"].queryset)
        self.assertNotIn(PlaceType.objects.get(code="historical"), POIForm().fields["poi_type"].queryset)

    def test_type_in_use_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            PlaceType.objects.get(code="historical").delete()

    def test_renamed_name_shows_on_pages_and_filter_works(self):
        PlaceType.objects.filter(code="historical").update(name="Old Stuff")
        self.assertContains(self.client.get(reverse("locations:poi_detail", args=[self.poi.slug])), "Old Stuff")
        page = self.client.get(reverse("locations:poi_list") + "?type=historical")
        self.assertEqual([p.name for p in page.context["page_obj"]], ["Old Bridge"])
        self.assertEqual(list(self.client.get(reverse("locations:poi_list") + "?type=museum").context["page_obj"]), [])


class PlaceListCountryFilterTests(TestCase):
    """The places list filters by country; only countries that have places are offered."""

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("boss", "boss@example.com", "pw-1234-abcd"))
        self.us = Country.objects.create(name="United States", slug="us", iso_code="US", iso3_code="USA",
                                         continent="North America", approval_status=APPROVED)
        self.ca = Country.objects.create(name="Canada", slug="ca", iso_code="CA", iso3_code="CAN",
                                         continent="North America", approval_status=APPROVED)
        Country.objects.create(name="Empty", slug="empty", iso_code="EM", iso3_code="EMP", continent="Europe",
                               approval_status=APPROVED)
        for country, place in ((self.us, "Arches"), (self.ca, "Bell Centre")):
            city = City.objects.create(name=f"{place} town", slug=f"{place}-town".lower().replace(" ", "-"),
                                       country=country, latitude=1, longitude=2, approval_status=APPROVED)
            POI.objects.create(name=place, slug=place.lower().replace(" ", "-"), city=city, latitude=1, longitude=2,
                               approval_status=APPROVED)

    def test_filter_and_choices(self):
        url = reverse("locations:poi_list")
        page = self.client.get(url)
        self.assertEqual([c.name for c in page.context["countries"]], ["Canada", "United States"])
        page = self.client.get(f"{url}?country={self.ca.pk}")
        self.assertEqual([p.name for p in page.context["page_obj"]], ["Bell Centre"])
        self.assertContains(page, f'value="{self.ca.pk}" selected')
        self.assertEqual(len(self.client.get(f"{url}?country=nonsense").context["page_obj"]), 2)

    def test_admin_filters_by_country(self):
        page = self.client.get(reverse("admin:locations_poi_changelist") + f"?city__country__id__exact={self.us.pk}")
        self.assertEqual(page.status_code, 200)
        self.assertEqual([p.name for p in page.context["cl"].result_list], ["Arches"])
