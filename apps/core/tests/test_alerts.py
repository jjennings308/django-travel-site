"""Error emails (site roadmap R3): wired in prod, nothing private in them, one per error an hour."""
import logging
import os
import runpy
import sys
from unittest import mock

from django.core import mail
from django.core.cache import caches
from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.core import alerts
from apps.core.alerts import AlertEmailHandler
from apps.core.settings_helpers import parse_admins

ALERT_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "alerts-test-default"},
    "alerts": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "alerts-test"},
}


class ParseAdminsTests(SimpleTestCase):
    def test_names_and_several_addresses(self):
        self.assertEqual(parse_admins("James <james@example.com>, ops@example.com"),
                         ["James <james@example.com>", "ops@example.com"])

    def test_empty_is_off(self):
        self.assertEqual(parse_admins(""), [])
        self.assertEqual(parse_admins("not an address"), [])


class ProdSettingsTests(SimpleTestCase):
    def test_django_request_errors_go_to_the_alert_handler(self):
        env = {"DJANGO_SECRET_KEY": "x" * 60, "DJANGO_ALLOWED_HOSTS": "example.com", "EMAIL_HOST": "localhost",
               "DJANGO_ADMINS": "James <james@example.com>"}
        with mock.patch.dict(os.environ, env):
            sys.modules.pop("config.settings.base", None)  # re-read DJANGO_ADMINS
            try:
                prod = runpy.run_module("config.settings.prod")
            finally:
                sys.modules.pop("config.settings.base", None)
        logging_config = prod["LOGGING"]
        self.assertEqual(logging_config["handlers"]["alert_email"]["class"], "apps.core.alerts.AlertEmailHandler")
        self.assertEqual(logging_config["loggers"]["django.request"]["handlers"], ["console", "alert_email"])
        self.assertEqual(prod["ADMINS"], ["James <james@example.com>"])
        self.assertIn("FileBasedCache", prod["CACHES"]["alerts"]["BACKEND"])


@override_settings(ADMINS=["James <james@example.com>"], CACHES=ALERT_CACHES,
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AlertEmailTests(SimpleTestCase):
    def setUp(self):
        caches["alerts"].clear()
        mail.outbox = []
        self.logger = logging.getLogger("test.alerts")
        self.logger.propagate = False
        self.handler = AlertEmailHandler(level=logging.ERROR)
        self.logger.addHandler(self.handler)
        self.addCleanup(self.logger.removeHandler, self.handler)

    def request(self):
        request = RequestFactory().post("/trips/7/edit/?token=SECRET-QUERY", {"passport": "X1234567"})
        request.user = mock.Mock(is_authenticated=True, pk=42)
        return request

    def fail(self, request=None, kind=ValueError):
        passport_number = "X1234567"  # a local variable that must not be mailed  # noqa: F841
        try:
            raise kind("boom")
        except kind:
            self.logger.error("Internal Server Error: /trips/7/edit/", exc_info=True,
                              extra={"request": request or self.request()})

    def test_email_has_path_and_user_but_nothing_private(self):
        self.fail()
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["James <james@example.com>"])
        self.assertIn("ValueError at", message.subject)
        self.assertIn("test_alerts.py", message.subject)
        self.assertIn("Path:    /trips/7/edit/", message.body)
        self.assertIn("User id: 42", message.body)
        self.assertIn("raise kind(\"boom\")", message.body)
        for secret in ("X1234567", "SECRET-QUERY", "passport_number"):
            self.assertNotIn(secret, message.body)
        self.assertEqual(message.alternatives, [])

    def test_one_email_per_error_per_hour_then_a_count(self):
        for _ in range(4):
            self.fail()
        self.assertEqual(len(mail.outbox), 1)
        self.fail(kind=KeyError)  # a different error mails at once
        self.assertEqual(len(mail.outbox), 2)
        # The hour passes: the guard key expires, and the next email reports the repeats.
        with mock.patch("apps.core.alerts.should_send", wraps=alerts.should_send) as spy:
            self.fail()
        caches["alerts"].delete(spy.call_args.args[0])
        self.fail()
        self.assertEqual(len(mail.outbox), 3)
        self.assertIn("Repeats: +4 more", mail.outbox[-1].body)

    @override_settings(ADMINS=[])
    def test_no_admins_no_email(self):
        self.fail()
        self.assertEqual(mail.outbox, [])

    def test_mail_failure_never_raises(self):
        with mock.patch("apps.core.alerts.mail_admins", side_effect=OSError("smtp down")), \
                mock.patch.object(self.handler, "handleError") as handled:
            self.fail()
        handled.assert_called_once()
