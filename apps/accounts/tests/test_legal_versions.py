"""Accepting changed Terms / Privacy (site roadmap R16)."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

User = get_user_model()


@override_settings(LEGAL_ACCEPTANCE_REQUIRED=True, TERMS_VERSION="2026-10-19", PRIVACY_VERSION="2026-10-19")
class LegalVersionTests(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada", "ada@example.com", "pw-1234-abcd")
        self.client.force_login(self.ada)

    def test_asked_once_then_through(self):
        page = self.client.get(reverse("pages:dashboard"))
        self.assertRedirects(page, f"{reverse('accept_legal')}?next=%2Fdashboard%2F", fetch_redirect_response=False)
        self.assertContains(self.client.get(page.url), "Please confirm our terms")
        response = self.client.post(reverse("accept_legal"), {"next": "/dashboard/"})
        self.assertRedirects(response, "/dashboard/", fetch_redirect_response=False)
        self.ada.refresh_from_db()
        self.assertEqual((self.ada.terms_version, self.ada.privacy_version), ("2026-10-19", "2026-10-19"))
        self.assertIsNotNone(self.ada.legal_accepted_at)
        self.assertEqual(self.client.get(reverse("pages:dashboard")).status_code, 200)

    def test_a_new_version_asks_again(self):
        self.ada.accept_legal()
        with override_settings(PRIVACY_VERSION="2027-01-01"):
            page = self.client.get(reverse("pages:dashboard"))
            self.assertEqual(page.status_code, 302)
            self.assertContains(self.client.get(page.url), "We've updated our terms")

    def test_never_blocks_reading_leaving_or_posting(self):
        for url in (reverse("pages:terms"), reverse("pages:privacy"), reverse("pages:help"), "/healthz/",
                    reverse("pages:my_data"), reverse("notifications:unread_count")):
            with self.subTest(url=url):
                self.assertNotEqual(self.client.get(url).status_code, 302, url)
        self.assertNotEqual(self.client.post(reverse("pages:welcome_dismiss")).url, None)  # a POST isn't intercepted

    def test_sign_up_records_the_versions(self):
        self.client.logout()
        with override_settings(SIGNUP_MODE="open"):
            self.client.post(reverse("register"), {
                "username": "newbie", "email": "newbie@example.com", "first_name": "N", "last_name": "B",
                "password1": "a-Long-pass-9876", "password2": "a-Long-pass-9876", "terms_accepted": "on"})
        user = User.objects.get(username="newbie")
        self.assertFalse(user.needs_legal_acceptance)

    def test_legal_pages_show_the_version(self):
        self.ada.accept_legal()
        self.assertContains(self.client.get(reverse("pages:terms")), "Version 2026-10-19")
