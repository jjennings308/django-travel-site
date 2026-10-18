"""Exchange rates: the ECB's daily reference rates, stored, and conversions (site roadmap R10).

The European Central Bank publishes, each working day around 16:00 CET, how many units of about 30
currencies one euro buys. ``fetch`` + ``parse`` + ``store`` (``manage.py fetch_rates``) keep them in
``ExchangeRate``; any pair is a cross rate through the euro.

``Rates`` answers conversions for one page in one query: build it with the currencies and dates the
page needs (and any per-trip overrides, ``{(from, to): rate}``), then ``convert`` says not just the
amount but how — the rate, its date and its source — so pages can show "≈" and the rate used. A
date with no rate on or before it (a future trip), or more than ``STALE_DAYS`` after the last rate,
uses the latest rate and says so. An unknown currency gives None, never a guess.
"""
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date as date_cls, timedelta
from decimal import ROUND_HALF_UP, Decimal
from urllib.request import Request, urlopen

from django.utils import timezone

ECB_BASE = "https://www.ecb.europa.eu/stats/eurofxref/"
FEEDS = {"daily": "eurofxref-daily.xml", "90d": "eurofxref-hist-90d.xml", "all": "eurofxref-hist.xml"}
NS = {"e": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}
STALE_DAYS = 4  # weekends and holidays have no rate; more than this means "latest", not "that day's"
CENT = Decimal("0.01")


class RatesError(Exception):
    pass


def fetch(feed="daily", timeout=20):
    """The ECB XML for ``feed`` (daily / 90d / all), or ``RatesError``."""
    request = Request(ECB_BASE + FEEDS[feed], headers={"User-Agent": "ShareBucketList rates (+https://sharebucketlist.com)"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - a fixed https URL
            return response.read()
    except OSError as exc:
        raise RatesError(f"Could not reach the ECB: {exc}") from exc


def parse(xml):
    """{date: {currency: per_euro}} from ECB XML, or ``RatesError`` if it isn't that."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise RatesError(f"Not ECB rates XML: {exc}") from exc
    days = {}
    for day in root.iterfind(".//e:Cube[@time]", NS):
        rates = {cube.get("currency"): Decimal(cube.get("rate")) for cube in day.iterfind("e:Cube[@currency]", NS)}
        if rates:
            days[date_cls.fromisoformat(day.get("time"))] = rates
    if not days:
        raise RatesError("The ECB file had no rates in it.")
    return days


def store(days):
    """Save parsed rates (new or corrected). Returns how many rows were written."""
    from .models import ExchangeRate
    rows = [ExchangeRate(date=day, currency=currency, per_euro=rate)
            for day, rates in days.items() for currency, rate in rates.items()]
    ExchangeRate.objects.bulk_create(rows, update_conflicts=True, unique_fields=["date", "currency"],
                                     update_fields=["per_euro"], batch_size=2000)
    return len(rows)


@dataclass(frozen=True)
class Conversion:
    amount: Decimal       # converted, to the cent
    rate: Decimal         # 1 from = rate to
    source: str           # "trip" (an editor's rate), "ECB", or "same"
    rate_date: object = None  # the ECB day used
    latest: bool = False  # True when the day's own rate wasn't there and the latest was used

    def describe(self, src, dst):
        if self.source == "same":
            return ""
        when = f", {self.rate_date:%b} {self.rate_date.day}" if self.rate_date else ""
        note = " (latest)" if self.latest else ""
        who = "this trip's rate" if self.source == "trip" else f"ECB{when}{note}"
        return f"1 {src} = {self.rate.normalize():f} {dst} ({who})"


class Rates:
    """ECB rates for ``currencies`` around ``dates`` (one query), plus a trip's ``overrides``."""

    def __init__(self, currencies, dates=(), overrides=None):
        from .models import ExchangeRate
        self.overrides = {(a.upper(), b.upper()): Decimal(r) for (a, b), r in (overrides or {}).items()}
        wanted = {c.upper() for c in currencies if c} - {"EUR"}
        self.table = {}  # currency -> [(date, per_euro)] newest first
        if not wanted:
            return
        today = timezone.localdate()
        known = [d for d in dates if d]
        low = min(known + [today]) - timedelta(days=14)  # no upper bound: there are no future rates
        rows = (ExchangeRate.objects.filter(currency__in=wanted, date__gte=low)
                .order_by("currency", "-date").values_list("currency", "date", "per_euro"))
        for currency, day, per_euro in rows:
            self.table.setdefault(currency, []).append((day, per_euro))

    def _per_euro(self, currency, on):
        if currency == "EUR":
            return Decimal(1), None, False
        rows = self.table.get(currency)
        if not rows:
            return None, None, False
        if on is None:
            return rows[0][1], rows[0][0], False
        for day, per_euro in rows:
            if day <= on:
                return per_euro, day, (on - day).days > STALE_DAYS
        return rows[0][1], rows[0][0], True

    def convert(self, amount, src, dst, on=None):
        """A ``Conversion`` of ``amount`` from ``src`` to ``dst`` on ``on``, or None if unknown."""
        if amount is None:
            return None
        src, dst, amount = (src or "").upper(), (dst or "").upper(), Decimal(amount)
        if not src or src == dst:
            return Conversion(amount.quantize(CENT, ROUND_HALF_UP), Decimal(1), "same")
        if (src, dst) in self.overrides:
            rate = self.overrides[(src, dst)]
            return Conversion((amount * rate).quantize(CENT, ROUND_HALF_UP), rate, "trip")
        if (dst, src) in self.overrides:
            rate = Decimal(1) / self.overrides[(dst, src)]
            return Conversion((amount * rate).quantize(CENT, ROUND_HALF_UP), rate, "trip")
        from_euro, from_day, from_latest = self._per_euro(src, on)
        to_euro, to_day, to_latest = self._per_euro(dst, on)
        if from_euro is None or to_euro is None:
            return None
        rate = to_euro / from_euro
        return Conversion((amount * rate).quantize(CENT, ROUND_HALF_UP), rate, "ECB",
                          from_day or to_day, from_latest or to_latest)
