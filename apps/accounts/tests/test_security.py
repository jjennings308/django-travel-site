"""Role-request documents are private; the theme cookie is locked down."""
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import RoleRequest

User = get_user_model()
PRIVATE = tempfile.mkdtemp(prefix="sbl-test-private-")
PUBLIC = tempfile.mkdtemp(prefix="sbl-test-media-")


@override_settings(PRIVATE_MEDIA_ROOT=PRIVATE, MEDIA_ROOT=PUBLIC)
class RoleDocumentTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(PRIVATE, ignore_errors=True)
        shutil.rmtree(PUBLIC, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.ada = User.objects.create_user("ada", "ada@example.com", "pw-1234-abcd")
        self.request = RoleRequest.objects.create(
            user=self.ada, requested_role=RoleRequest.RequestedRole.VENDOR,
            supporting_documents=SimpleUploadedFile("licence.pdf", b"%PDF-1.4 secret", content_type="application/pdf"))
        self.url = reverse("role_request_document", args=[self.request.pk])

    def test_stored_outside_media(self):
        name = self.request.supporting_documents.name
        self.assertTrue((Path(PRIVATE) / name).exists())
        self.assertFalse((Path(PUBLIC) / name).exists())
        with self.assertRaises(ValueError):
            self.request.supporting_documents.url  # no public URL at all

    def test_requester_and_staff_may_download(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4 secret")
        self.assertIn("attachment", response["Content-Disposition"])
        staffer = User.objects.create_user("staffer", "s@example.com", "pw-1234-abcd")
        staffer.user_permissions.add(Permission.objects.get(codename="can_access_staff_dashboard", content_type__app_label="accounts"))
        self.client.force_login(User.objects.get(pk=staffer.pk))
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertContains(self.client.get(reverse("staff:admin_role_request_detail", args=[self.request.pk])), self.url)

    def test_others_get_404_and_anonymous_must_log_in(self):
        self.client.force_login(User.objects.create_user("bob", "bob@example.com", "pw-1234-abcd"))
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_admin_change_page_links_the_view(self):
        boss = User.objects.create_superuser("boss", "b@example.com", "pw-1234-abcd")
        self.client.force_login(boss)
        page = self.client.get(reverse("admin:accounts_rolerequest_change", args=[self.request.pk]))
        self.assertContains(page, self.url)


class ThemeCookieTests(TestCase):
    def test_cookie_flags(self):
        cookie = self.client.get(reverse("pages:about"), secure=True).cookies["ui_theme"]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
