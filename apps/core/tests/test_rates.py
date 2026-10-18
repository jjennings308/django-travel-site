"""ECB exchange rates and conversions (site roadmap R10)."""
import io
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.core import rates
from apps.core.models import ExchangeRate

SAMPLE = (Path(__file__).parent / "data" / "ecb_sample.xml").read_bytes()


class ParseStoreTests(TestCase):
    def test_parse_the_ecb_file(self):
        days = rates.parse(SAMPLE)
        self.assertEqual(sorted(days), [date(2027, 9, 17), date(2027, 9, 20)])
        self.assertEqual(days[date(2027, 9, 20)]["USD"], Decimal("1.1000"))

    def test_store_is_idempotent_and_corrects(self):
        rates.store(rates.parse(SAMPLE))
        rates.store({date(2027, 9, 20): {"USD": Decimal("1.1100")}})
        self.assertEqual(ExchangeRate.objects.count(), 6)
        self.assertEqual(ExchangeRate.objects.get(date=date(2027, 9, 20), currency="USD").per_euro, Decimal("1.11"))

    def test_garbage_is_refused(self):
        for bad in (b"<html>maintenance</html>", b"not xml at all"):
            with self.assertRaises(rates.RatesError):
                rates.parse(bad)

    def test_command_stores_and_refuses_a_bad_download(self):
        with mock.patch("apps.core.rates.fetch", return_value=SAMPLE) as fetch:
            out = io.StringIO()
            call_command("fetch_rates", "--history", "90d", stdout=out)
        fetch.assert_called_once_with("90d")
        self.assertIn("newest 2027-09-20", out.getvalue())
        ExchangeRate.objects.all().delete()
        with mock.patch("apps.core.rates.fetch", side_effect=rates.RatesError("offline")):
            with self.assertRaises(CommandError):
                call_command("fetch_rates", stdout=io.StringIO())
        self.assertFalse(ExchangeRate.objects.exists())


class ConvertTests(TestCase):
    def setUp(self):
        rates.store(rates.parse(SAMPLE))

    def test_uses_the_rate_on_or_before_the_day(self):
        table = rates.Rates(["USD", "GBP"], [date(2027, 9, 18)])
        conversion = table.convert(Decimal("100"), "EUR", "USD", on=date(2027, 9, 18))  # a Saturday-ish gap
        self.assertEqual(conversion.amount, Decimal("108.00"))
        self.assertEqual((conversion.source, conversion.rate_date, conversion.latest), ("ECB", date(2027, 9, 17), False))
        later = table.convert(Decimal("100"), "EUR", "USD", on=date(2027, 9, 20))
        self.assertEqual(later.amount, Decimal("110.00"))

    def test_cross_rates_through_the_euro(self):
        table = rates.Rates(["USD", "GBP"], [date(2027, 9, 20)])
        conversion = table.convert(Decimal("85"), "GBP", "USD", on=date(2027, 9, 20))
        self.assertEqual(conversion.amount, Decimal("110.00"))
        self.assertTrue(conversion.describe("GBP", "USD").startswith("1 GBP = 1.29"))

    def test_a_future_day_uses_the_latest_and_says_so(self):
        table = rates.Rates(["USD"], [date(2028, 5, 1)])
        conversion = table.convert(Decimal("10"), "EUR", "USD", on=date(2028, 5, 1))
        self.assertEqual((conversion.amount, conversion.latest), (Decimal("11.00"), True))
        self.assertIn("(latest)", conversion.describe("EUR", "USD"))

    def test_a_trip_rate_wins_both_ways(self):
        table = rates.Rates(["USD"], [date(2027, 9, 20)], overrides={("EUR", "USD"): Decimal("1.25")})
        self.assertEqual(table.convert(Decimal("100"), "EUR", "USD", on=date(2027, 9, 20)).amount, Decimal("125.00"))
        back = table.convert(Decimal("125"), "USD", "EUR")
        self.assertEqual((back.amount, back.source), (Decimal("100.00"), "trip"))
        self.assertEqual(back.describe("USD", "EUR"), "1 USD = 0.8 EUR (this trip's rate)")

    def test_unknown_currency_is_none_and_same_is_free(self):
        table = rates.Rates(["USD", "XYZ"])
        self.assertIsNone(table.convert(Decimal("1"), "XYZ", "USD"))
        same = table.convert(Decimal("9.999"), "usd", "USD")
        self.assertEqual((same.amount, same.source, same.describe("USD", "USD")), (Decimal("10.00"), "same", ""))

    def test_one_query_for_a_page(self):
        with self.assertNumQueries(1):
            table = rates.Rates(["USD", "GBP", "JPY"], [date(2027, 9, 17), date(2027, 9, 20)])
        with self.assertNumQueries(0):
            for currency in ("USD", "GBP", "JPY"):
                table.convert(Decimal("1"), "EUR", currency, on=date(2027, 9, 20))
