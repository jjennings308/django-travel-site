"""HEIC uploads are stored as JPEG (browsers other than Safari can't show HEIC),
upright and without metadata; Media records the stored JPEG's type and size."""
import io
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from apps.media_app.models import Media

MEDIA_ROOT = tempfile.mkdtemp(prefix="sbl-test-media-")


def heic_upload(name="IMG_0001.HEIC", size=(40, 30), exif=None):
    buf = io.BytesIO()
    kwargs = {"exif": exif} if exif is not None else {}
    Image.new("RGB", size, "red").save(buf, format="HEIF", **kwargs)
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/heic")


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class HeicUploadTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = get_user_model().objects.create_user("u", "u@example.com", "pw-1234-abcd")

    def test_media_upload_is_stored_as_jpeg(self):
        media = Media.objects.create(file=heic_upload(), uploaded_by=self.user)
        self.assertTrue(media.file.name.endswith(".jpg"))
        self.assertEqual((media.file_extension, media.mime_type, media.media_type), ("jpg", "image/jpeg", "image"))
        self.assertEqual(media.file_size, media.file.size)
        with Image.open(media.file.path) as image:
            self.assertEqual((image.format, image.size), ("JPEG", (40, 30)))

    def test_orientation_applied_and_metadata_dropped(self):
        exif = Image.Exif()
        exif[0x0112] = 6  # orientation: rotate 90° clockwise to display
        exif[0x010F] = "PhoneMaker"
        media = Media.objects.create(file=heic_upload(size=(40, 30), exif=exif.tobytes()), uploaded_by=self.user)
        with Image.open(media.file.path) as image:
            self.assertEqual(image.size, (30, 40))
            self.assertEqual(dict(image.getexif()), {})

    def test_avatar_is_stored_as_jpeg(self):
        from apps.accounts.models import Profile
        profile, _ = Profile.objects.get_or_create(user=self.user)
        profile.avatar = heic_upload("me.heic")
        profile.save()
        self.assertTrue(profile.avatar.name.endswith("/me.jpg"))
        with Image.open(profile.avatar.path) as image:
            self.assertEqual(image.format, "JPEG")

    def test_other_formats_untouched(self):
        buf = io.BytesIO()
        Image.new("RGB", (10, 10)).save(buf, format="PNG")
        media = Media.objects.create(file=SimpleUploadedFile("a.png", buf.getvalue()), uploaded_by=self.user)
        self.assertTrue(media.file.name.endswith(".png"))
