"""The staging settings and the disguise applied to its copy of production (site roadmap R16)."""
import os
import runpy
import sys
from datetime import date
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
User = get_user_model()


class StagingSettingsTests(TestCase):
    def test_never_sends_mail_says_staging_and_noindex(self):
        env = {"DJANGO_SECRET_KEY": "s" * 20 + "-staging-not-a-real-key-0123456789abcdef", "DJANGO_ALLOWED_HOSTS":
               "staging.sharebucketlist.com", "EMAIL_HOST": "smtp.example.com"}
        with mock.patch.dict(os.environ, env):
            sys.modules.pop("config.settings.base", None)
            try:
                staging = runpy.run_module("config.settings.staging")
            finally:
                sys.modules.pop("config.settings.base", None)
        self.assertEqual(staging["EMAIL_BACKEND"], "django.core.mail.backends.console.EmailBackend")
        self.assertTrue(staging["STAGING"])
        self.assertIn("apps.core.middleware.NoIndexMiddleware", staging["MIDDLEWARE"])
        self.assertIn("LocMemCache", staging["CACHES"]["ratelimit"]["BACKEND"])  # never production's /tmp files

    def test_the_bar_and_robots_tag(self):
        from django.test import override_settings
        with override_settings(STAGING=True, MIDDLEWARE=[*__import__("django.conf").conf.settings.MIDDLEWARE,
                                                         "apps.core.middleware.NoIndexMiddleware"]):
            page = self.client.get("/")
        self.assertContains(page, "data-staging-bar")
        self.assertEqual(page["X-Robots-Tag"], "noindex, nofollow")
        self.assertNotContains(self.client.get("/"), "data-staging-bar")
