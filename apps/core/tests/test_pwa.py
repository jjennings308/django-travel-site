"""The installable / offline pieces served by core (site roadmap R6)."""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.core.pwa import offline_cache_key

User = get_user_model()


class ServedTests(TestCase):
    def test_service_worker(self):
        response = self.client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/javascript; charset=utf-8")
        self.assertIn("no-cache", response["Cache-Control"])
        self.assertEqual(response["Service-Worker-Allowed"], "/trips/")
        body = response.content.decode()
        self.assertIn('"sbl-offline-"', body)
        self.assertIn("data-sbl-offline hidden", body)  # what it switches on in a saved page

    def test_manifest(self):
        response = self.client.get("/manifest.webmanifest")
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        data = json.loads(response.content)
        self.assertEqual(data["start_url"], "/trips/")
        self.assertEqual({icon["sizes"] for icon in data["icons"]}, {"192x192", "512x512"})
        from django.conf import settings
        from django.contrib.staticfiles import finders
        for icon in data["icons"]:
            self.assertIsNotNone(finders.find(icon["src"].removeprefix(settings.STATIC_URL)), icon["src"])


class ShellTests(TestCase):
    def test_every_page_links_the_manifest(self):
        self.assertContains(self.client.get("/"), 'rel="manifest"')

    def test_signed_out_pages_clear_saved_trips(self):
        html = self.client.get("/accounts/login/").content.decode()
        self.assertIn("clearSaved();", html)

    def test_signed_in_pages_clear_only_on_logout(self):
        user = User.objects.create_user("ada", "ada@example.com", "pw-1234-abcd")
        self.client.force_login(user)
        html = self.client.get("/help/").content.decode()
        self.assertNotIn("clearSaved();", html)
        self.assertIn('var logoutPath = "/accounts/logout/"', html)


class CacheKeyTests(TestCase):
    def test_per_person_and_opaque(self):
        ada = User.objects.create_user("ada", "ada@example.com", "pw-1234-abcd")
        bob = User.objects.create_user("bob", "bob@example.com", "pw-1234-abcd")
        self.assertNotEqual(offline_cache_key(ada), offline_cache_key(bob))
        self.assertEqual(offline_cache_key(ada), offline_cache_key(ada))
        self.assertNotIn(str(ada.pk), offline_cache_key(ada)[:2])
        self.assertRegex(offline_cache_key(ada), r"^[0-9a-f]{20}$")
