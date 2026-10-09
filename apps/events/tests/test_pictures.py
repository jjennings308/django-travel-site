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
