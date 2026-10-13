"""Trip photo albums: who sees, adds, removes and picks the cover; never on the shared link."""
import io
import shutil
import tempfile
from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.media_app.models import AlbumMedia, Media
from apps.trips.models import Trip, TripGrant, TripRole

User = get_user_model()
MEDIA_ROOT = tempfile.mkdtemp(prefix="sbl-test-trip-photos-")


def photo(name="p.jpg"):
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "teal").save(buf, format="JPEG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class TripPhotoTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.commentor = User.objects.create_user("co", "co@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.stranger = User.objects.create_user("st", "st@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Rome", start_date=date(2027, 4, 1), end_date=date(2027, 4, 8),
                                        created_by=self.editor)
        for user, role in ((self.editor, TripRole.EDITOR), (self.commentor, TripRole.COMMENTOR), (self.viewer, TripRole.VIEWER)):
            TripGrant.objects.create(trip=self.trip, user=user, role=role)
        self.url = reverse("trips:trip_photos", args=[self.trip.pk])

    def upload(self, user, *names):
        self.client.force_login(user)
        response = self.client.post(self.url, {"photos": [photo(n) for n in names]})
        self.trip.refresh_from_db()
        return response

    def test_commentor_adds_and_first_photo_is_the_cover(self):
        self.assertRedirects(self.upload(self.commentor, "a.jpg", "b.jpg"), self.url)
        self.trip.refresh_from_db()
        items = list(self.trip.photos())
        self.assertEqual(len(items), 2)
        self.assertEqual(self.trip.album.cover_image, items[0].media)
        self.assertEqual((items[0].media.uploaded_by, items[0].media.content_object), (self.commentor, self.trip))
        self.upload(self.editor, "c.jpg")
        self.assertEqual(self.trip.photos().count(), 3)
        self.assertEqual(Trip.objects.get(pk=self.trip.pk).album_id, self.trip.album_id)  # one album

    def test_viewer_sees_but_cannot_add(self):
        self.upload(self.editor, "a.jpg")
        self.client.force_login(self.viewer)
        page = self.client.get(self.url)
        self.assertContains(page, Media.objects.get().file.url)
        self.assertNotContains(page, 'name="photos"')
        self.assertEqual(self.client.post(self.url, {"photos": [photo()]}).status_code, 403)

    def test_no_grant_is_404(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_remove_by_uploader_or_editor_and_cover_moves_on(self):
        self.upload(self.commentor, "a.jpg", "b.jpg")
        first, second = [i.media for i in self.trip.photos()]
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(reverse("trips:trip_photo_delete", args=[self.trip.pk, first.pk])).status_code, 403)
        self.client.force_login(self.commentor)
        self.client.post(reverse("trips:trip_photo_delete", args=[self.trip.pk, first.pk]))
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.album.cover_image, second)
        self.client.force_login(self.editor)
        self.client.post(reverse("trips:trip_photo_delete", args=[self.trip.pk, second.pk]))
        self.assertFalse(AlbumMedia.objects.exists())

    def test_only_editors_pick_the_cover(self):
        self.upload(self.commentor, "a.jpg", "b.jpg")
        second = list(self.trip.photos())[1].media
        cover_url = reverse("trips:trip_photo_cover", args=[self.trip.pk, second.pk])
        self.client.force_login(self.commentor)
        self.assertEqual(self.client.post(cover_url).status_code, 403)
        self.client.force_login(self.editor)
        self.client.post(cover_url)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.album.cover_image, second)

    def test_photos_of_another_trip_are_404(self):
        other = Trip.objects.create(name="Paris", start_date=date(2027, 5, 1), end_date=date(2027, 5, 3), created_by=self.editor)
        TripGrant.objects.create(trip=other, user=self.editor, role=TripRole.EDITOR)
        self.upload(self.editor, "a.jpg")
        media = Media.objects.get()
        self.assertEqual(self.client.post(reverse("trips:trip_photo_delete", args=[other.pk, media.pk])).status_code, 404)

    def test_detail_links_photos_and_public_view_leaves_them_out(self):
        self.upload(self.editor, "a.jpg")
        self.assertContains(self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])), self.url)
        self.trip.enable_public()
        self.client.logout()
        public = self.client.get(reverse("public_trip", args=[self.trip.public_token]))
        self.assertEqual(public.status_code, 200)
        self.assertNotContains(public, Media.objects.get().file.url)
        self.assertNotContains(public, self.url)
