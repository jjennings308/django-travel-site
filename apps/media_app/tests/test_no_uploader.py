"""A picture with no uploader — a country's flag, or one whose uploader deleted their account (R13 sets
``uploaded_by`` to NULL) — still has a label. (The admin pages that list pictures: pages/tests/test_admin_media.py.)"""

import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.media_app.models import Media


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="sbl-test-media-"))
class NoUploaderTests(TestCase):
    def test_label(self):
        root = get_user_model().objects.create_user("root", "root@example.com", "pw-1234-abcd")
        media = Media.objects.create(
            file=SimpleUploadedFile("flag.png", b"\x89PNG\r\n\x1a\n", content_type="image/png"),
            media_type="image",
            uploaded_by=root,
        )
        name = media.file.name.rsplit("/", 1)[-1]  # uploads are stored under a random name
        self.assertEqual(str(media), f"{name} by root")
        Media.objects.filter(pk=media.pk).update(uploaded_by=None)  # as account deletion does (SET_NULL)
        media.refresh_from_db()
        self.assertEqual(str(media), name)
