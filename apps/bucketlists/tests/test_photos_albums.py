"""Goal photos at any stage, and personal albums (My albums)."""
import io
import shutil
import tempfile
from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.bucketlists.models import BucketListItem
from apps.media_app.models import AlbumMedia, Media, MediaAlbum
from apps.trips.models import Trip, TripGrant, TripRole

User = get_user_model()
MEDIA_ROOT = tempfile.mkdtemp(prefix="sbl-test-goal-photos-")


def photo(name="p.jpg"):
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "olive").save(buf, format="JPEG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class PhotoFixture(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.alice = User.objects.create_user("alice", "alice@example.com", "pw-1234-abcd")
        self.bob = User.objects.create_user("bob", "bob@example.com", "pw-1234-abcd")
        self.item = BucketListItem.objects.create(user=self.alice, custom_title="See the northern lights")
        self.client.force_login(self.alice)


class GoalPhotoTests(PhotoFixture):
    def test_add_photos_before_the_goal_is_done(self):
        url = reverse("bucketlists:item_photos", args=[self.item.pk])
        self.assertRedirects(self.client.post(url, {"photos": [photo("a.jpg"), photo("b.jpg")]}), url)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, "wishlist")
        self.assertEqual(self.item.photos().count(), 2)
        page = self.client.get(reverse("bucketlists:dashboard"))
        self.assertContains(page, self.item.photos().first().file.url)  # card shows its photo
        self.assertContains(page, url)

    def test_private_to_the_owner(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(reverse("bucketlists:item_photos", args=[self.item.pk])).status_code, 404)

    def test_delete_a_photo_also_leaves_albums(self):
        self.item.add_photos([photo()], self.alice)
        media = self.item.photos().get()
        album = MediaAlbum.objects.create(user=self.alice, title="Lights", privacy="private")
        album.add([media])
        self.client.post(reverse("bucketlists:item_photo_delete", args=[self.item.pk, media.pk]))
        self.assertFalse(self.item.photos().exists())
        album.refresh_from_db()
        self.assertIsNone(album.cover_image)
        self.assertFalse(AlbumMedia.objects.exists())


class AlbumTests(PhotoFixture):
    def make(self, **data):
        self.client.post(reverse("bucketlists:album_new"), {"title": "Parks 2026", "description": "", "privacy": "private", **data})
        return MediaAlbum.objects.get(title="Parks 2026")

    def test_make_and_pick_from_goals_and_trips(self):
        self.item.add_photos([photo("goal.jpg")], self.alice)
        trip = Trip.objects.create(name="Moab", start_date=date(2026, 9, 1), end_date=date(2026, 9, 5), created_by=self.alice)
        TripGrant.objects.create(trip=trip, user=self.alice, role=TripRole.EDITOR)
        trip.add_photos([photo("trip.jpg")], self.alice)
        trip.add_photos([photo("bobs.jpg")], self.bob)  # someone else's photo is not offered
        album = self.make()
        pick = self.client.get(reverse("bucketlists:album_pick", args=[album.pk]))
        offered = list(pick.context["available"])
        self.assertEqual({m.uploaded_by_id for m in offered}, {self.alice.pk})
        self.assertEqual(len(offered), 2)
        self.client.post(reverse("bucketlists:album_pick", args=[album.pk]), {"media": [m.pk for m in offered]})
        album.refresh_from_db()
        self.assertEqual(album.items().count(), 2)
        self.assertIsNotNone(album.cover_image)
        self.assertNotIn(album, MediaAlbum.objects.filter(trip__isnull=False))
        page = self.client.get(reverse("bucketlists:albums"))
        self.assertContains(page, "Parks 2026")
        self.assertNotContains(page, "Moab photos")  # trip albums are not personal albums

    def test_upload_into_album_and_take_out(self):
        album = self.make()
        self.client.post(reverse("bucketlists:album_detail", args=[album.pk]), {"photos": [photo("up.jpg")]})
        self.item.add_photos([photo("goal.jpg")], self.alice)
        album.add([self.item.photos().get()])
        uploaded, borrowed = [e.media for e in album.items()]
        self.client.post(reverse("bucketlists:album_remove", args=[album.pk, uploaded.pk]))
        self.assertFalse(Media.objects.filter(pk=uploaded.pk).exists())  # uploaded into the album: deleted
        self.client.post(reverse("bucketlists:album_remove", args=[album.pk, borrowed.pk]))
        self.assertTrue(Media.objects.filter(pk=borrowed.pk).exists())   # borrowed from the goal: stays
        self.assertFalse(album.items().exists())

    def test_delete_album_keeps_borrowed_photos(self):
        album = self.make()
        self.client.post(reverse("bucketlists:album_detail", args=[album.pk]), {"photos": [photo("up.jpg")]})
        self.item.add_photos([photo("goal.jpg")], self.alice)
        album.add([self.item.photos().get()])
        self.client.post(reverse("bucketlists:album_delete", args=[album.pk]))
        self.assertFalse(MediaAlbum.objects.exists())
        self.assertEqual(list(Media.objects.values_list("pk", flat=True)), [self.item.photos().get().pk])

    def test_who_sees_an_album(self):
        self.alice.profile_visibility = "private"
        self.alice.save()
        album = self.make()
        url = reverse("bucketlists:album_detail", args=[album.pk])
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(url).status_code, 404)              # private
        album.privacy = "public"
        album.save()
        self.assertEqual(self.client.get(url).status_code, 404)              # public album, private profile
        self.alice.profile_visibility = "public"
        self.alice.save()
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, reverse("bucketlists:album_edit", args=[album.pk]))
        self.assertContains(self.client.get(reverse("bucketlists:public_list", args=["alice"])), url)
        self.assertEqual(self.client.post(reverse("bucketlists:album_delete", args=[album.pk])).status_code, 404)
        self.assertEqual(self.client.post(url, {"photos": [photo()]}).status_code, 404)

    def test_trip_album_not_reachable_as_personal(self):
        trip = Trip.objects.create(name="Moab", start_date=date(2026, 9, 1), end_date=date(2026, 9, 5), created_by=self.alice)
        trip.add_photos([photo()], self.alice)
        trip.refresh_from_db()
        self.assertEqual(self.client.get(reverse("bucketlists:album_detail", args=[trip.album_id])).status_code, 404)
