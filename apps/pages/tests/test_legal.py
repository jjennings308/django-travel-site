from django.test import TestCase, override_settings
from django.urls import reverse

FILLED = {
    "entity": "Example Travel LLC", "contact_email": "privacy@example.com", "postal_address": "1 Main St",
    "jurisdiction": "Pennsylvania, USA", "effective_date": "October 8, 2026", "min_age": "16",
}


class LegalPageTests(TestCase):
    def test_pages_are_public(self):
        for name, heading in [("terms", "Terms of Service"), ("privacy", "Privacy Policy"), ("safety", "Safety")]:
            with self.subTest(name=name):
                response = self.client.get(reverse(f"pages:{name}"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'<h1 class="sbl-page-title">{heading}</h1>', html=False)

    def test_footer_links_to_all_three(self):
        response = self.client.get(reverse("pages:about"))
        for name in ["terms", "privacy", "safety"]:
            self.assertContains(response, f'href="{reverse(f"pages:{name}")}"')

    @override_settings(LEGAL={**FILLED, "entity": "[Legal entity name]"})
    def test_draft_banner_while_placeholders_remain(self):
        self.assertContains(self.client.get(reverse("pages:privacy")), "This page is a template")

    @override_settings(LEGAL=FILLED)
    def test_filled_details_replace_placeholders_and_banner(self):
        response = self.client.get(reverse("pages:privacy"))
        self.assertNotContains(response, "This page is a template")
        self.assertContains(response, "Example Travel LLC")
        self.assertContains(response, "mailto:privacy@example.com")
        self.assertNotContains(response, "[Legal entity name]")
