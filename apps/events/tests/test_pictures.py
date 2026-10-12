"""Optional pictures on events and activities: upload on the form, scaled down,
shown on the page; removable; next year's copy of an event keeps the picture."""
import io
import shutil
import tempfile
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from apps.activities.models import Activity
from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event
from apps.media_app.forms import MAX_PICTURE_SIDE

from .test_events import EventFixture

MEDIA_ROOT = tempfile.mkdtemp(prefix="sbl-test-pictures-")


def picture(name="photo.jpg", size=(800, 600), fmt="JPEG"):
    buf = io.BytesIO()
    Image.new("RGB", size, "blue").save(buf, format=fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type=f"image/{fmt.lower()}")


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class PictureTests(EventFixture):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def test_event_picture_is_optional(self):
        self.client.force_login(self.alice)
        self.client.post(reverse("events:event_add"), self.payload())
        self.assertIsNone(Event.objects.get(name="Jazz Night").featured_media)

    def test_event_upload_shows_and_can_be_removed(self):
        self.client.force_login(self.alice)
        self.client.post(reverse("events:event_add"), {**self.payload(), "picture": picture()})
        event = Event.objects.get(name="Jazz Night")
        media = event.featured_media
        self.assertEqual((media.uploaded_by, media.media_type, media.content_object), (self.alice, "image", event))
        self.assertContains(self.client.get(reverse("events:event_detail", args=[event.slug])), media.file.url)
        self.client.post(reverse("events:event_edit", args=[event.slug]), {**self.payload(), "remove_picture": "on"})
        event.refresh_from_db()
        self.assertIsNone(event.featured_media)

    def test_large_picture_is_scaled_down(self):
        self.client.force_login(self.staff)
        self.client.post(reverse("events:event_add"), {**self.payload(), "picture": picture("big.png", (4000, 1000), "PNG")})
        media = Event.objects.get(name="Jazz Night").featured_media
        with Image.open(media.file.path) as image:
            self.assertEqual((image.format, image.size), ("PNG", (MAX_PICTURE_SIDE, 600)))

    def test_not_an_image_is_refused(self):
        self.client.force_login(self.alice)
        bad = SimpleUploadedFile("notes.jpg", b"not an image", content_type="image/jpeg")
        response = self.client.post(reverse("events:event_add"), {**self.payload(), "picture": bad})
        self.assertFalse(Event.objects.exists())
        self.assertContains(response, "Upload a valid image")

    def test_next_years_copy_keeps_the_picture(self):
        okto = Activity.objects.create(category=self.music, name="Okto", description="d", created_by=self.bob,
                                       recurrence="yearly", visibility="public", approval_status=ApprovalStatus.APPROVED)
        self.client.force_login(self.staff)
        self.client.post(reverse("events:event_add"), {**self.payload(name="Okto 2027", related_activity=okto.pk,
                                                       start_date="2027-09-18"), "picture": picture()})
        first = Event.objects.get(name="Okto 2027")
        self.client.post(reverse("events:event_add") + f"?copy={first.pk}",
                         self.payload(name="Okto 2028", related_activity=okto.pk, start_date="2028-09-16"))
        self.assertEqual(Event.objects.get(name="Okto 2028").featured_media, first.featured_media)

    def test_activity_picture(self):
        activity = Activity.objects.create(category=self.music, name="Gig", description="d", created_by=self.alice,
                                           visibility="private")
        self.client.force_login(self.alice)
        data = {"category": self.music.pk, "name": "Gig", "description": "d", "specificity_level": "general",
                "skill_level": "any", "fitness_required": 1, "duration_category": "varies", "cost_level": "varies",
                "best_for": "any", "indoor_outdoor": "both", "risk_level": "low", "picture": picture()}
        self.client.post(reverse("activities:activity_edit", args=[activity.slug]), data)
        activity.refresh_from_db()
        self.assertIsNotNone(activity.featured_media)
        self.assertContains(self.client.get(reverse("activities:activity_detail", args=[activity.slug])),
                            activity.featured_media.file.url)


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class ActivityPictureCopyTests(EventFixture):
    """A new event starts with its activity's picture; the event can replace or remove its own."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        from apps.media_app.models import Media
        self.activity = Activity.objects.create(category=self.music, name="Okto", description="d", created_by=self.bob,
                                                recurrence="yearly", visibility="public",
                                                approval_status=ApprovalStatus.APPROVED)
        self.media = Media(file=picture(), uploaded_by=self.bob, media_type="image", title="Okto", content_object=self.activity)
        self.media.save()
        self.activity.featured_media = self.media
        self.activity.save()

    def add(self, **extra):
        self.client.force_login(self.staff)
        self.client.post(reverse("events:event_add"), {**self.payload(name="Okto 2027", related_activity=self.activity.pk,
                                                                       start_date="2027-09-18"), **extra})
        return Event.objects.get(name="Okto 2027")

    def test_new_event_gets_the_activity_picture(self):
        event = self.add()
        self.assertEqual(event.featured_media, self.media)
        self.assertContains(self.client.get(reverse("events:event_detail", args=[event.slug])), self.media.file.url)

    def test_created_anywhere(self):  # CSV import and admin save through the model too
        event = self.make("Okto 2028", related_activity=self.activity)
        self.assertEqual(event.featured_media, self.media)
        self.assertIsNone(self.make("Other").featured_media)

    def test_upload_replaces_it_for_the_event_only(self):
        event = self.add(picture=picture("own.jpg"))
        self.assertNotEqual(event.featured_media, self.media)
        self.client.post(reverse("events:event_edit", args=[event.slug]),
                         {**self.payload(name="Okto 2027", related_activity=self.activity.pk, start_date="2027-09-18"),
                          "picture": picture("later.jpg")})
        event.refresh_from_db()
        self.assertTrue(event.featured_media.file.name.endswith(".jpg"))
        self.assertNotEqual(event.featured_media, self.media)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.featured_media, self.media)

    def test_removed_picture_stays_removed(self):
        event = self.add()
        self.client.post(reverse("events:event_edit", args=[event.slug]),
                         {**self.payload(name="Okto 2027", related_activity=self.activity.pk, start_date="2027-09-18"),
                          "remove_picture": "on"})
        event.refresh_from_db()
        self.assertIsNone(event.featured_media)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.featured_media, self.media)

    def test_copy_keeps_last_years_picture_over_the_activitys(self):
        first = self.add(picture=picture("2027.jpg"))
        self.client.post(reverse("events:event_add") + f"?copy={first.pk}",
                         self.payload(name="Okto 2028", related_activity=self.activity.pk, start_date="2028-09-16"))
        self.assertEqual(Event.objects.get(name="Okto 2028").featured_media, first.featured_media)
