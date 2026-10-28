"""The booklet's cover photo (``Trip.cover_photo``): uploaded in Settings or picked on Photos, by editors only;
printed on the PDF's cover as an embedded picture; never on the shared link."""
import base64
import io
import shutil
import tempfile
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.trips import pdf
from apps.trips.models import Trip, TripGrant, TripRole

User = get_user_model()
MEDIA_ROOT = tempfile.mkdtemp(prefix="sbl-test-trip-cover-")


def picture(name="cover.jpg", size=(3000, 1500)):
    buf = io.BytesIO()
    Image.new("RGB", size, "teal").save(buf, format="JPEG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class CoverPhotoTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.commentor = User.objects.create_user("co", "co@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Rome", start_date=date(2027, 4, 1), end_date=date(2027, 4, 8),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.commentor, role=TripRole.COMMENTOR)
        self.cover_url = reverse("trips:trip_cover", args=[self.trip.pk])

    def booklet_html(self, user):
        self.client.force_login(user)
        with mock.patch.object(pdf, "render_pdf", side_effect=lambda html, **kw: html.encode()) as render:
            self.client.get(reverse("trips:trip_pdf", args=[self.trip.pk]))
        return render.call_args.args[0]

    def test_settings_upload_joins_the_photos_and_prints_on_the_cover(self):
        self.assertNotIn('class="cover-photo"', self.booklet_html(self.editor))
        self.client.force_login(self.editor)
        response = self.client.post(self.cover_url, {"photo": picture()})
        self.assertRedirects(response, reverse("trips:trip_settings", args=[self.trip.pk]) + "#cover",
                             fetch_redirect_response=False)
        self.trip.refresh_from_db()
        self.assertIsNotNone(self.trip.cover_photo)
        self.assertEqual([item.media for item in self.trip.photos()], [self.trip.cover_photo])
        settings_page = self.client.get(reverse("trips:trip_settings", args=[self.trip.pk])).content.decode()
        self.assertIn("data-cover-photo", settings_page)
        html = self.booklet_html(self.editor)
        self.assertIn('class="cover with-photo"', html)
        data = html.split('class="cover-photo" src="data:image/jpeg;base64,', 1)[1].split('"', 1)[0]
        with Image.open(io.BytesIO(base64.b64decode(data))) as embedded:
            self.assertEqual(max(embedded.size), pdf.COVER_SIDE)  # scaled for the page, not the full upload

    def test_take_it_off_keeps_the_photo(self):
        self.client.force_login(self.editor)
        self.client.post(self.cover_url, {"photo": picture()})
        self.client.post(self.cover_url, {"remove": "1"})
        self.trip.refresh_from_db()
        self.assertIsNone(self.trip.cover_photo)
        self.assertEqual(self.trip.photos().count(), 1)

    def test_pick_on_photos_and_removing_the_photo_clears_it(self):
        self.client.force_login(self.commentor)
        self.client.post(reverse("trips:trip_photos", args=[self.trip.pk]), {"photos": [picture("a.jpg"), picture("b.jpg")]})
        self.trip.refresh_from_db()
        second = list(self.trip.photos())[1].media
        pick = reverse("trips:trip_photo_booklet", args=[self.trip.pk, second.pk])
        self.assertEqual(self.client.post(pick).status_code, 403)  # editors only
        self.client.force_login(self.editor)
        photos_page = self.client.get(reverse("trips:trip_photos", args=[self.trip.pk])).content.decode()
        self.assertIn(pick, photos_page)
        self.client.post(pick)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.cover_photo, second)
        self.assertIn("data-booklet-cover", self.client.get(reverse("trips:trip_photos", args=[self.trip.pk])).content.decode())
        self.client.post(reverse("trips:trip_photo_delete", args=[self.trip.pk, second.pk]))
        self.trip.refresh_from_db()
        self.assertIsNone(self.trip.cover_photo)

    def test_only_editors_upload(self):
        self.client.force_login(self.commentor)
        self.assertEqual(self.client.post(self.cover_url, {"photo": picture()}).status_code, 403)
        self.assertIsNone(Trip.objects.get(pk=self.trip.pk).cover_photo_id)

    def test_not_a_picture_is_refused(self):
        self.client.force_login(self.editor)
        bad = SimpleUploadedFile("x.jpg", b"not an image", content_type="image/jpeg")
        response = self.client.post(self.cover_url, {"photo": bad}, follow=True)
        self.assertIsNone(Trip.objects.get(pk=self.trip.pk).cover_photo_id)
        self.assertContains(response, "Upload a valid image")

    def test_an_unreadable_file_leaves_the_cover_plain(self):
        self.client.force_login(self.editor)
        self.client.post(self.cover_url, {"photo": picture()})
        self.trip.refresh_from_db()
        self.trip.cover_photo.file.storage.delete(self.trip.cover_photo.file.name)
        with self.assertLogs("apps.trips.pdf", "WARNING"):
            self.assertNotIn('class="cover-photo"', self.booklet_html(self.editor))
