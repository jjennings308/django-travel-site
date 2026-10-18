"""Tickets and documents on confirmations (site roadmap R5)."""
import io
import os
import shutil
import tempfile
from datetime import date
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.trips import files
from apps.trips.models import Confirmation, ConfirmationFile, Lodging, Trip, TripGrant, TripRole

User = get_user_model()
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def image_bytes(fmt):
    out = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(out, format=fmt)
    return out.getvalue()


class FilesFixture(TestCase):
    def setUp(self):
        self.private = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.private, ignore_errors=True)
        override = override_settings(PRIVATE_MEDIA_ROOT=self.private)
        override.enable()
        self.addCleanup(override.disable)
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.commentor = User.objects.create_user("co", "co@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.stranger = User.objects.create_user("st", "st@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Rome", start_date=date(2027, 5, 1), end_date=date(2027, 5, 4),
                                        created_by=self.editor)
        for user, role in ((self.editor, TripRole.EDITOR), (self.commentor, TripRole.COMMENTOR),
                           (self.viewer, TripRole.VIEWER)):
            TripGrant.objects.create(trip=self.trip, user=user, role=role)
        self.stay = Lodging.objects.create(trip=self.trip, name="Hotel Roma", check_in=date(2027, 5, 1),
                                           check_out=date(2027, 5, 4))
        self.confirmation = Confirmation.attach_number(self.trip, "ROMA1", self.stay, provider="Booking.com")
        self.add_url = reverse("trips:confirmation_file_add", args=[self.trip.pk, self.confirmation.pk])

    def upload(self, name, content, user=None, content_type="application/octet-stream"):
        self.client.force_login(user or self.editor)
        return self.client.post(self.add_url, {"files": SimpleUploadedFile(name, content, content_type)})

    def only_file(self):
        return ConfirmationFile.objects.get()


class UploadTests(FilesFixture):
    def test_pdf_png_jpeg(self):
        for name, content, kind in (("pass.pdf", PDF, "application/pdf"), ("map.png", image_bytes("PNG"), "image/png"),
                                    ("ticket.jpeg", image_bytes("JPEG"), "image/jpeg")):
            self.upload(name, content)
            record = ConfirmationFile.objects.get(original_name__startswith=os.path.splitext(name)[0])
            self.assertEqual(record.content_type, kind)
            self.assertEqual(record.size, len(content))
            self.assertEqual(record.uploaded_by, self.editor)
        self.assertEqual(ConfirmationFile.objects.get(content_type="image/jpeg").original_name, "ticket.jpg")

    def test_heic_is_stored_as_jpeg(self):
        out = io.BytesIO()
        Image.new("RGB", (40, 30), "blue").save(out, format="HEIF")
        self.upload("IMG_0001.HEIC", out.getvalue())
        record = self.only_file()
        self.assertEqual((record.original_name, record.content_type), ("IMG_0001.jpg", "image/jpeg"))
        self.assertTrue(record.file.name.endswith(".jpg"))
        with record.file.open("rb") as stored:
            self.assertEqual(Image.open(stored).format, "JPEG")

    def test_contents_decide_not_the_name(self):
        response = self.upload("boarding-pass.pdf", b"<html><script>alert(1)</script></html>")
        self.assertFalse(ConfirmationFile.objects.exists())
        self.assertIn("only PDF, PNG, JPEG", [str(m) for m in response.wsgi_request._messages][0])
        self.upload("pic.gif", image_bytes("GIF"))
        self.assertFalse(ConfirmationFile.objects.exists())
        self.upload("not-really.png", PDF)  # a real PDF named .png is stored as a PDF
        self.assertEqual(self.only_file().original_name, "not-really.pdf")

    def test_per_file_limit(self):
        with mock.patch.object(files, "MAX_FILE_MB", 0.0001):
            self.upload("big.pdf", PDF + b"x" * 200)
        self.assertFalse(ConfirmationFile.objects.exists())

    def test_per_trip_limit(self):
        self.upload("one.pdf", PDF)
        with mock.patch.object(files, "MAX_TRIP_MB", (len(PDF) * 1.5) / files.MB):
            self.upload("two.pdf", PDF)
        self.assertEqual(ConfirmationFile.objects.count(), 1)

    def test_several_at_once(self):
        self.client.force_login(self.editor)
        self.client.post(self.add_url, {"files": [SimpleUploadedFile("a.pdf", PDF), SimpleUploadedFile("b.pdf", PDF)]})
        self.assertEqual(ConfirmationFile.objects.count(), 2)

    def test_stored_privately_under_the_trip(self):
        self.upload("pass.pdf", PDF)
        record = self.only_file()
        self.assertRegex(record.file.name, rf"^trips/{self.trip.pk}/[0-9a-f]{{32}}\.pdf$")
        self.assertTrue(record.file.path.startswith(self.private))
        self.assertFalse(record.file.path.startswith(str(settings.MEDIA_ROOT)))
        with self.assertRaises(ValueError):
            record.file.url  # private storage has no public URL

    def test_only_editors_upload(self):
        self.assertEqual(self.upload("pass.pdf", PDF, user=self.commentor).status_code, 403)
        self.assertEqual(self.upload("pass.pdf", PDF, user=self.stranger).status_code, 404)
        self.assertFalse(ConfirmationFile.objects.exists())

    def test_another_trips_confirmation_is_a_404(self):
        other = Trip.objects.create(name="Paris", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        TripGrant.objects.create(trip=other, user=self.editor, role=TripRole.EDITOR)
        self.client.force_login(self.editor)
        url = reverse("trips:confirmation_file_add", args=[other.pk, self.confirmation.pk])
        self.assertEqual(self.client.post(url, {"files": SimpleUploadedFile("a.pdf", PDF)}).status_code, 404)


class DownloadAndDeleteTests(FilesFixture):
    def setUp(self):
        super().setUp()
        self.upload("Boarding Pass.pdf", PDF)
        self.record = self.only_file()
        self.url = reverse("trips:confirmation_file", args=[self.trip.pk, self.record.pk])

    def test_viewer_downloads_inline_with_safe_headers(self):
        self.client.force_login(self.viewer)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), PDF)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn('inline; filename="Boarding Pass.pdf"', response["Content-Disposition"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Content-Security-Policy"], "sandbox")
        self.assertIn("no-store", response["Cache-Control"])

    def test_outsiders_and_wrong_trip_get_404(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)  # to login
        other = Trip.objects.create(name="Paris", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        TripGrant.objects.create(trip=other, user=self.viewer, role=TripRole.VIEWER)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("trips:confirmation_file", args=[other.pk, self.record.pk])).status_code,
                         404)

    def test_remove_deletes_the_stored_file(self):
        path = self.record.file.path
        self.assertTrue(os.path.exists(path))
        self.client.force_login(self.commentor)
        delete = reverse("trips:confirmation_file_delete", args=[self.trip.pk, self.record.pk])
        self.assertEqual(self.client.post(delete).status_code, 403)
        self.client.force_login(self.editor)
        self.client.post(delete)
        self.assertFalse(ConfirmationFile.objects.exists())
        self.assertFalse(os.path.exists(path))

    def test_deleting_the_confirmation_deletes_its_files(self):
        path = self.record.file.path
        self.client.force_login(self.editor)
        self.client.post(reverse("trips:confirmation_delete", args=[self.trip.pk, self.confirmation.pk]))
        self.assertFalse(ConfirmationFile.objects.exists())
        self.assertFalse(os.path.exists(path))


class ShownTests(FilesFixture):
    def setUp(self):
        super().setUp()
        self.upload("ticket.pdf", PDF)
        self.record = self.only_file()
        self.link = reverse("trips:confirmation_file", args=[self.trip.pk, self.record.pk])

    def test_trip_page_reference_link_and_chip_count(self):
        self.client.force_login(self.viewer)
        html = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        self.assertIn(self.link, html)
        self.assertIn("📎 ticket.pdf", html)
        self.assertIn("ROMA1 · Booking.com · 📎1", html)

    def test_edit_page_and_item_block(self):
        self.client.force_login(self.editor)
        page = self.client.get(reverse("trips:confirmation_edit", args=[self.trip.pk, self.confirmation.pk]))
        self.assertContains(page, "Tickets &amp; documents")
        self.assertContains(page, self.link)
        self.assertContains(page, 'enctype="multipart/form-data"')
        block = self.client.get(reverse("trips:item_confirmations", args=[self.trip.pk, "stay", self.stay.pk]))
        self.assertContains(block, self.link)
        self.assertContains(block, "Add a file")

    def test_booklet_lists_file_names(self):
        captured = {}

        def fake(html, base_url):
            captured["html"] = html
            return b"%PDF"

        self.client.force_login(self.viewer)
        with mock.patch("apps.trips.pdf.render_pdf", side_effect=fake):
            self.client.get(reverse("trips:trip_pdf", args=[self.trip.pk]))
        self.assertIn("Files: ticket.pdf", captured["html"])

    def test_never_public(self):
        self.client.logout()  # drop the editor's "Added ticket.pdf" message from setUp
        self.trip.enable_public()
        html = self.client.get(reverse("public_trip", args=[self.trip.public_token])).content.decode()
        self.assertNotIn("ticket.pdf", html)
        self.assertNotIn("/files/", html)
