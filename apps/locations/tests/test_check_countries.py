"""The monthly country check against REST Countries (docs/plans/country-flags.md, C2). No network: ``urlopen`` is
patched with small hand-written answers in the API's shape (not a copy of their data)."""
import io
import json
import urllib.error
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from apps.locations import restcountries
from apps.locations.models import Country

KEY = "rc_test_key"


def country(a2, a3, common, currencies, calling, continents, official="", alternates=()):
    return {"names": {"common": common, "official": official or common, "alternates": list(alternates)},
            "codes": {"alpha_2": a2, "alpha_3": a3}, "currencies": currencies, "calling_codes": calling,
            "continents": continents}


THEIRS = [
    country("DE", "DEU", "Germany", {"EUR": {"name": "Euro", "symbol": "€"}}, ["49"], ["Europe"]),
    country("ZW", "ZWE", "Zimbabwe", {"ZWG": {"name": "Zimbabwe Gold"}}, ["263"], ["Africa"]),
    country("CH", "CHE", "Switzerland", {"CHF": {"name": "Swiss franc"}, "CHE": {"name": "WIR euro"}}, ["41"],
            ["Europe"]),
    country("AG", "ATG", "Antigua and Barbuda", {"XCD": {"name": "East Caribbean Dollar"}}, ["1268"],
            ["North America"]),
    country("PR", "PRI", "Puerto Rico", {"USD": {"name": "US Dollar"}}, ["1787"], ["North America"]),
]


class Answer:
    """What ``urlopen`` returns: a context manager with ``read()``."""

    def __init__(self, payload):
        self.body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


def page(objects, more=False, offset=0):
    return Answer({"data": {"objects": objects, "meta": {"total": 5, "count": len(objects), "limit": 100,
                                                          "offset": offset, "more": more}}})


def http_error(code, retry_after=None):
    headers = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError("https://api.restcountries.com/countries/v5", code, "error", headers,
                                  io.BytesIO(b"{}"))


def ours(**extra):
    defaults = [("Germany", "DE", "DEU", "EUR", "Euro", "+49", "Europe"),
                ("Zimbabwe", "ZW", "ZWE", "ZWL", "Zimbabwean Dollar", "+263", "Africa"),
                ("Switzerland", "CH", "CHE", "CHF", "Swiss franc", "+41", "Europe"),
                ("Antigua and Barbuda", "AG", "ATG", "XCD", "East Caribbean Dollar", "+1-268", "North America")]
    for name, a2, a3, code, money, phone, continent in defaults:
        Country.objects.create(name=name, slug=a2.lower(), iso_code=a2, iso3_code=a3, currency_code=code,
                               currency_name=money, phone_code=phone, continent=continent)


@override_settings(RESTCOUNTRIES_API_KEY=KEY)
class CheckTests(TestCase):
    def setUp(self):
        ours()

    def run_check(self, *args, answers=None):
        out, err = StringIO(), StringIO()
        with mock.patch("apps.locations.restcountries.urllib.request.urlopen",
                        side_effect=answers or [page(THEIRS)]) as urlopen:
            try:
                call_command("check_countries", *args, stdout=out, stderr=err)
                code = 0  # finished normally: nothing differs
            except SystemExit as stop:
                code = stop.code
        return out.getvalue(), err.getvalue(), code, urlopen

    def test_differences_are_printed_and_exit_1(self):
        out, _, code, urlopen = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("ZW currency_code: ours ZWL, theirs ZWG", out)
        self.assertNotIn("DE ", out.split("Notes:")[0].replace("Compared", ""))  # Germany matches
        self.assertNotIn("AG phone_code", out)  # +1-268 is 1268
        self.assertIn("CH also uses CHE (ours: CHF)", out)  # several currencies: a note, not a difference
        self.assertIn("Theirs we don't have (1): PR", out)
        self.assertIn("1 to look at.", out)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), f"Bearer {KEY}")
        self.assertNotIn(KEY, request.full_url)
        self.assertIn("response_fields=", request.full_url)

    def test_each_field(self):
        Country.objects.filter(iso_code="DE").update(name="Deutschland", iso3_code="GER", currency_name="Mark",
                                                     phone_code="+4", continent="Asia")
        out, _, code, _ = self.run_check()
        for line in ("DE name: ours Deutschland, theirs Germany", "DE iso3_code: ours GER, theirs DEU",
                     "DE currency_name: ours Mark, theirs Euro", "DE phone_code: ours +4, theirs +49",
                     "DE continent: ours Asia, theirs Europe"):
            self.assertIn(line, out)

    def test_an_official_or_alternate_name_matches(self):
        Country.objects.filter(iso_code="DE").update(name="Federal Republic of Germany")
        theirs = [country("DE", "DEU", "Germany", {"EUR": {"name": "Euro"}}, ["49"], ["Europe"],
                          official="Federal Republic of Germany")]
        out, _, code, _ = self.run_check("--country", "DE", answers=[page(theirs)])
        self.assertEqual(code, 0)
        self.assertIn("No differences.", out)

    def test_ours_they_dont_know(self):
        Country.objects.create(name="Nowhere", slug="nowhere", iso_code="QQ", iso3_code="QQQ", continent="Europe")
        out, _, code, _ = self.run_check()
        self.assertIn("Ours they don't know (1): QQ Nowhere", out)
        self.assertEqual(code, 1)

    def test_nothing_differs_exit_0(self):
        Country.objects.filter(iso_code="ZW").update(currency_code="ZWG", currency_name="Zimbabwe Gold")
        out, _, code, _ = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("No differences.", out)

    def test_pages_until_no_more(self):
        out, _, code, urlopen = self.run_check(answers=[page(THEIRS[:3], more=True), page(THEIRS[3:], offset=3)])
        self.assertEqual(urlopen.call_count, 2)
        self.assertIn("offset=3", urlopen.call_args.args[0].full_url)
        self.assertIn("ZW currency_code", out)

    def test_currencies_as_a_list(self):
        self.assertEqual(restcountries.currencies([{"code": "eur", "name": "Euro"}]), [("EUR", "Euro")])
        self.assertEqual(restcountries.currencies({"code": "USD", "name": "US Dollar"}), [("USD", "US Dollar")])

    def test_429_waits_then_carries_on(self):
        with mock.patch("apps.locations.restcountries.time.sleep") as sleep:
            out, _, code, urlopen = self.run_check(answers=[http_error(429, "3"), http_error(429), page(THEIRS)])
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [3, restcountries.WAIT])
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(code, 1)

    def test_403_and_401_stop_with_exit_2(self):
        _, err, code, _ = self.run_check(answers=[http_error(403)])
        self.assertEqual(code, 2)
        self.assertIn("monthly quota is used up", err)
        _, err, code, _ = self.run_check(answers=[http_error(401)])
        self.assertEqual(code, 2)
        self.assertIn("check RESTCOUNTRIES_API_KEY", err)
        self.assertNotIn(KEY, err)

    @override_settings(RESTCOUNTRIES_API_KEY="")
    def test_a_missing_key_is_exit_2_without_a_request(self):
        _, err, code, urlopen = self.run_check()
        self.assertEqual(code, 2)
        self.assertIn("RESTCOUNTRIES_API_KEY isn't set", err)
        urlopen.assert_not_called()

    def test_nothing_is_saved(self):
        with CaptureQueriesContext(connection) as ctx:
            self.run_check()
        writes = [q["sql"] for q in ctx.captured_queries if q["sql"].lstrip().upper().startswith(
            ("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(writes, [])
