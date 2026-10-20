"""Visit statistics: the self-hosted Umami script, production only, never on a secret address."""
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.core.context_processors import site_branding

SCRIPT = "https://analytics.example.test/script.js"
ON = {"ANALYTICS_SCRIPT_URL": SCRIPT, "ANALYTICS_WEBSITE_ID": "site-id-123"}


class AnalyticsTests(TestCase):
    def test_off_unless_configured(self):
        response = self.client.get(reverse("pages:home"))
        self.assertNotContains(response, "data-website-id")

    @override_settings(**ON)
    def test_both_bases_load_it_without_query_strings(self):
        response = self.client.get(reverse("pages:home"))  # base_marketing.html
        self.assertContains(response, f'<script defer src="{SCRIPT}" data-website-id="site-id-123" '
                                      'data-exclude-search="true" data-exclude-hash="true" '
                                      'data-do-not-track="true"></script>', html=False)
        user = get_user_model().objects.create_user("stats", "stats@example.com", "pw-12345678")
        self.client.force_login(user)
        response = self.client.get(reverse("pages:dashboard"))  # base.html
        self.assertContains(response, 'data-website-id="site-id-123"')

    @override_settings(**ON)
    def test_never_on_an_address_holding_a_secret(self):
        factory = RequestFactory()
        for path in ("/public/0b8e7c1e-5d0a-4f43-9d8e-1a2b3c4d5e6f/", "/trips/invite/abc/",
                     "/accounts/reset/MQ/set-password/", "/accounts/verify-email/MQ/abc-def/",
                     "/notifications/unsubscribe/abc/"):
            self.assertEqual(site_branding(factory.get(path))["ANALYTICS_SCRIPT_URL"], "", path)
        self.assertEqual(site_branding(factory.get("/trips/5/"))["ANALYTICS_SCRIPT_URL"], SCRIPT)
