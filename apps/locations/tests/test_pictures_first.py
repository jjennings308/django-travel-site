"""Location lists put places with a picture first, then their usual order."""
import io
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import POI, City, Country
from apps.media_app.models import Media

APPROVED = ApprovalStatus.APPROVED
MEDIA_ROOT = tempfile.mkdtemp(prefix="sbl-test-pictures-first-")


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class PicturesFirstTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = get_user_model().objects.create_user("u", "u@example.com", "pw-1234-abcd")
        self.client.force_login(self.user)
        self.country = Country.objects.create(name="Testland", slug="testland", iso_code="TL", iso3_code="TLD",
                                              continent="Europe", approval_status=APPROVED)
        self.aaa = City.objects.create(name="Aaaville", slug="aaa", country=self.country, latitude=1, longitude=2, approval_status=APPROVED)
        self.zzz = City.objects.create(name="Zzzton", slug="zzz", country=self.country, latitude=1, longitude=2, approval_status=APPROVED)
        self.zzz.featured_media = Media.objects.create(file=self.jpeg(), uploaded_by=self.user, media_type="image", title="z")
        self.zzz.save()
        self.a_poi = POI.objects.create(name="Arch", slug="arch", city=self.aaa, latitude=1, longitude=2, approval_status=APPROVED)
        self.z_poi = POI.objects.create(name="Zoo", slug="zoo", city=self.aaa, latitude=1, longitude=2, approval_status=APPROVED,
                                        featured_media=self.zzz.featured_media)

    @staticmethod
    def jpeg():
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), "red").save(buf, format="JPEG")
        return SimpleUploadedFile("x.jpg", buf.getvalue(), content_type="image/jpeg")

    def names(self, url, key):
        return [obj.name for obj in self.client.get(url).context[key]]

    def test_lists_and_detail_pages(self):
        self.assertEqual(self.names(reverse("locations:city_list"), "page_obj")[:2], ["Zzzton", "Aaaville"])
        self.assertEqual(self.names(reverse("locations:poi_list"), "page_obj")[:2], ["Zoo", "Arch"])
        self.assertEqual(self.names(reverse("locations:country_detail", args=["testland"]), "cities")[:2], ["Zzzton", "Aaaville"])
        self.assertEqual(self.names(reverse("locations:city_detail", args=["aaa"]), "pois")[:2], ["Zoo", "Arch"])
