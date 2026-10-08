"""HEIC/HEIF (iPhone photos) open in Pillow once core registers pillow-heif."""
import io

from django import forms
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image


def heic_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, format="HEIF")
    return buf.getvalue()


class HeifTests(SimpleTestCase):
    def test_pillow_opens_heic(self):
        image = Image.open(io.BytesIO(heic_bytes()))
        self.assertEqual((image.format, image.size), ("HEIF", (40, 30)))

    def test_image_field_accepts_a_heic_upload(self):
        upload = SimpleUploadedFile("photo.heic", heic_bytes(), content_type="image/heic")
        self.assertEqual(forms.ImageField().clean(upload).name, "photo.heic")
