"""apps.core.geocoding: one Nominatim lookup, identifying itself, never raising."""
import json
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from apps.core.geocoding import geocode


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@override_settings(GEOCODING_ENABLED=True, GEOCODER_URL="https://geo.example/search", SITE_URL="https://sbl.example",
                   LEGAL={"contact_email": "hello@sbl.example"})
class GeocodeTests(SimpleTestCase):
    @mock.patch("apps.core.geocoding.urllib.request.urlopen")
    def test_found(self, urlopen):
        urlopen.return_value = FakeResponse([{"lat": "35.6870231", "lon": "-105.9378"}])
        self.assertEqual(geocode("125 Washington Ave,\n Santa Fe"), (Decimal("35.687023"), Decimal("-105.937800")))
        request = urlopen.call_args.args[0]
        self.assertIn("q=125+Washington+Ave%2C+Santa+Fe", request.full_url)
        self.assertIn("email=hello%40sbl.example", request.full_url)
        self.assertIn("https://sbl.example", request.get_header("User-agent"))
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 5)

    @mock.patch("apps.core.geocoding.urllib.request.urlopen")
    def test_not_found_and_errors_return_none(self, urlopen):
        urlopen.return_value = FakeResponse([])
        self.assertIsNone(geocode("Nowhere at all"))
        urlopen.side_effect = OSError("timed out")
        self.assertIsNone(geocode("Somewhere"))

    @mock.patch("apps.core.geocoding.urllib.request.urlopen")
    def test_blank_or_disabled_does_nothing(self, urlopen):
        self.assertIsNone(geocode("   "))
        with self.settings(GEOCODING_ENABLED=False):
            self.assertIsNone(geocode("Liverpool"))
        urlopen.assert_not_called()


class OffDuringTestsTest(SimpleTestCase):
    def test_disabled_under_manage_py_test(self):
        self.assertFalse(settings.GEOCODING_ENABLED)
