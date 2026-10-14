# core/geocoding.py
"""Turn a street address into coordinates, for placing private things (trip stays) on maps.

Uses OpenStreetMap's Nominatim by default (``settings.GEOCODER_URL``). Its usage policy:
at most one request a second, an identifying User-Agent, and no bulk geocoding -- so this
is called once when a stay's address is saved (``trips.Lodging.locate``) and by the
``geocode_stays`` backfill, which waits a second between requests. Only the address is
sent, never who is staying. Off when ``settings.GEOCODING_ENABLED`` is false (the test
run turns it off, so the suite never calls the network). Failures are logged, never raised.
"""
import json
import logging
import urllib.parse
import urllib.request
from decimal import Decimal

from django.conf import settings

log = logging.getLogger(__name__)
TIMEOUT = 5  # seconds


def geocode(address):
    """(latitude, longitude) as Decimals rounded to 6 places, or None."""
    address = " ".join((address or "").split())
    if not address or not getattr(settings, "GEOCODING_ENABLED", False):
        return None
    params = {"q": address, "format": "jsonv2", "limit": 1}
    contact = str(getattr(settings, "LEGAL", {}).get("contact_email", ""))
    if contact and not contact.startswith("["):
        params["email"] = contact
    url = f"{settings.GEOCODER_URL}?{urllib.parse.urlencode(params)}"
    agent = f"{getattr(settings, 'SITE_NAME', 'ShareBucketList')}/1.0 (+{getattr(settings, 'SITE_URL', '')})"
    request = urllib.request.Request(url, headers={"User-Agent": agent, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            results = json.loads(response.read().decode("utf-8"))
        if not results:
            return None
        q = Decimal("0.000001")
        return Decimal(results[0]["lat"]).quantize(q), Decimal(results[0]["lon"]).quantize(q)
    except Exception:  # noqa: BLE001 - a lookup failing must never break saving a stay
        log.warning("Geocoding failed for an address", exc_info=True)
        return None
