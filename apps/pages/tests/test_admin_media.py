"""The admin change pages of places list every picture in their Featured media select; one with no uploader (a
country's flag, or a deleted account's) used to 500 them (Media.__str__ read uploaded_by.username)."""

import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import POI, City, Country, Region
from apps.media_app.models import Media


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="sbl-test-media-"))
class PlaceAdminWithUploaderlessPictureTests(TestCase):
    def test_change_pages_load(self):
        admin = get_user_model().objects.create_superuser("root", "root@example.com", "pw-1234-abcd")
        media = Media.objects.create(
            file=SimpleUploadedFile("flag.png", b"\x89PNG\r\n\x1a\n", content_type="image/png"),
            media_type="image",
            uploaded_by=admin,
        )
        Media.objects.filter(pk=media.pk).update(uploaded_by=None)
        name = media.file.name.rsplit("/", 1)[-1]
        country = Country.objects.create(
            name="Testland", slug="testland", iso_code="TL", iso3_code="TLD", approval_status=ApprovalStatus.APPROVED
        )
        region = Region.objects.create(name="Testshire", slug="testshire", country=country)
        city = City.objects.create(
            name="Testville", slug="testville", country=country, region=region, latitude=1, longitude=2
        )
        poi = POI.objects.create(name="Old Bridge", slug="old-bridge", city=city, latitude=1, longitude=2)
        self.client.force_login(admin)
        for model, obj in (("poi", poi), ("city", city), ("region", region), ("country", country)):
            with self.subTest(model):
                response = self.client.get(reverse(f"admin:locations_{model}_change", args=[obj.pk]))
                self.assertContains(response, name)
