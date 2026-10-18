"""/healthz/ (site roadmap R3): 200 ok, 503 unavailable, no details either way."""
from unittest import mock

from django.db.utils import OperationalError
from django.test import TestCase
from django.urls import reverse


class HealthzTests(TestCase):
    url = "/healthz/"

    def test_ok(self):
        self.assertEqual(reverse("healthz"), self.url)
        response = self.client.get(self.url)
        self.assertEqual((response.status_code, response.content), (200, b"ok"))
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertIn("no-store", response["Cache-Control"])

    def test_database_down(self):
        with mock.patch("apps.core.health.connection.cursor", side_effect=OperationalError("could not connect")), \
                self.assertLogs("apps.core.health", "WARNING"):
            response = self.client.get(self.url)
        self.assertEqual((response.status_code, response.content), (503, b"unavailable"))
        self.assertNotIn(b"connect", response.content)

    def test_static_manifest_missing(self):
        with mock.patch("apps.core.health.staticfiles_storage.url",
                        side_effect=ValueError("Missing staticfiles manifest entry")), \
                self.assertLogs("apps.core.health", "WARNING"):
            response = self.client.get(self.url)
        self.assertEqual((response.status_code, response.content), (503, b"unavailable"))

    def test_signed_out_works_and_no_page_template(self):
        response = self.client.get(self.url)
        self.assertNotIn(b"<script", response.content)
        self.assertFalse(response.templates)
