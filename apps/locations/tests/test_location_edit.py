"""Edit pages for regions, cities and places: staff or the submitter; others are sent back."""
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import POI, City, Country, Region

User = get_user_model()
MEDIA_ROOT = tempfile.mkdtemp(prefix="sbl-test-location-edit-")


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class LocationEditTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.staff = User.objects.create_user("staff", "staff@example.com", "pw-1234-abcd", is_staff=True)
        self.member = User.objects.create_user("member", "member@example.com", "pw-1234-abcd")
        self.submitter = User.objects.create_user("sub", "sub@example.com", "pw-1234-abcd")
        self.us = Country.objects.create(name="United States", slug="us", iso_code="US", iso3_code="USA",
                                         continent="North America", approval_status=ApprovalStatus.APPROVED)
        self.other = Country.objects.create(name="Canada", slug="ca", iso_code="CA", iso3_code="CAN",
                                            continent="North America", approval_status=ApprovalStatus.APPROVED)
        self.region = Region.objects.create(country=self.us, name="Utah", code="UT", slug="utah",
                                            approval_status=ApprovalStatus.APPROVED)
        self.quebec = Region.objects.create(country=self.other, name="Quebec", code="QC", slug="quebec")
        self.city = City.objects.create(name="Moab", slug="moab-ut-us", country=self.us, region=self.region,
                                        latitude=38.57, longitude=-109.55, approval_status=ApprovalStatus.APPROVED,
                                        submitted_by=self.submitter)
        self.poi = POI.objects.create(name="Arches", slug="arches", city=self.city, latitude=38.7, longitude=-109.6,
                                      approval_status=ApprovalStatus.APPROVED)

    def city_data(self, **over):
        data = {"country": self.us.pk, "region": self.region.pk, "name": "Moab", "latitude": "38.57",
                "longitude": "-109.55", "timezone": "America/Denver", "elevation_m": "", "population": "5300",
                "capital_type": "", "best_time_to_visit": "Spring", "average_daily_budget": "",
                "description": "Red rock country."}
        data.update(over)
        return data

    def test_staff_edits_each_kind(self):
        self.client.force_login(self.staff)
        self.client.post(reverse("locations:region_edit", args=[self.region.slug]),
                         {"country": self.us.pk, "name": "Utah", "code": "UT", "latitude": "", "longitude": "",
                          "description": "Beehive State"})
        self.region.refresh_from_db()
        self.assertEqual(self.region.description, "Beehive State")

        response = self.client.post(reverse("locations:city_edit", args=[self.city.slug]), self.city_data())
        self.assertRedirects(response, reverse("locations:city_detail", args=[self.city.slug]))
        self.city.refresh_from_db()
        self.assertEqual((self.city.population, self.city.description), (5300, "Red rock country."))
        self.assertEqual(self.city.approval_status, ApprovalStatus.APPROVED)  # unchanged

        self.client.post(reverse("locations:poi_edit", args=[self.poi.slug]),
                         {"city": self.city.pk, "name": "Arches National Park", "poi_type": self.poi.poi_type_id,
                          "latitude": "38.7", "longitude": "-109.6", "website": "https://nps.gov/arch",
                          "entry_fee_currency": "USD", "wheelchair_accessible": "on"})
        self.poi.refresh_from_db()
        self.assertEqual((self.poi.name, self.poi.wheelchair_accessible, self.poi.slug),
                         ("Arches National Park", True, "arches"))  # slug kept, so links don't break

    def test_region_must_be_in_the_country(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse("locations:city_edit", args=[self.city.slug]),
                                    self.city_data(region=self.quebec.pk))
        self.assertContains(response, "Quebec is not in United States.")

    def test_picture_upload(self):
        import io
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (40, 30), "red").save(buf, format="JPEG")
        self.client.force_login(self.staff)
        self.client.post(reverse("locations:city_edit", args=[self.city.slug]),
                         {**self.city_data(), "picture": SimpleUploadedFile("moab.jpg", buf.getvalue(), "image/jpeg")})
        self.city.refresh_from_db()
        self.assertIsNotNone(self.city.featured_media)
        self.assertEqual(self.city.featured_media.content_object, self.city)

    def test_who_may_edit(self):
        url = reverse("locations:city_edit", args=[self.city.slug])
        detail = reverse("locations:city_detail", args=[self.city.slug])
        self.client.force_login(self.member)
        self.assertRedirects(self.client.get(url), detail)
        self.assertNotContains(self.client.get(detail), url)
        self.client.force_login(self.submitter)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(detail), url)
        for name, obj in (("region", self.region), ("poi", self.poi)):
            self.assertContains(self.client.get(reverse(f"locations:{name}_detail", args=[obj.slug])),
                                reverse(f"locations:{name}_edit", args=[obj.slug]))
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)  # to login
