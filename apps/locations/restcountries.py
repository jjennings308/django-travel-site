"""Read REST Countries (https://restcountries.com) for the monthly country check (country-flags plan C2).

Their terms (section 5) allow keeping their data for at most three days, so nothing here is stored: ``fetch``
returns plain dicts kept in memory for one ``check_countries`` run. Nothing from them is shown on the site.

``urllib.request`` like ``core.geocoding`` (no ``requests``). The key (``settings.RESTCOUNTRIES_API_KEY``) goes in
the ``Authorization: Bearer`` header, never in a URL, and is never logged. The free plan is 1,000 requests a month
and 20 per 10 seconds: every country is read with ``response_fields`` (only what we compare) in pages of 100 —
three requests — or one for ``--country``. A 429 waits and retries; a 403 (monthly quota used up, or a frozen
account) and a 401 (key) stop with ``ApiError``.

Response (v5): ``{"data": {"objects": [...], "meta": {"total", "count", "limit", "offset", "more"}}}``; each object
has ``names.common`` / ``official`` / ``alternates``, ``codes.alpha_2`` / ``alpha_3``, ``currencies`` (an object —
read either keyed by code ``{"EUR": {"name": …}}`` or as a list of ``{"code", "name"}``), ``calling_codes`` (strings)
and ``continents`` (strings).
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

BASE = "https://api.restcountries.com/countries/v5"
FIELDS = ("names.common,names.official,names.alternates,codes.alpha_2,codes.alpha_3,currencies,calling_codes,"
          "continents")
PAGE = 100  # the free plan's largest page
TIMEOUT = 20  # seconds
RETRIES = 3  # after a 429
WAIT = 11  # seconds before retrying a 429 without Retry-After (their window is 10 seconds)


class ApiError(Exception):
    """The API couldn't be read; the message says why (never the key)."""


def _get(path, params, key, sleep=None):
    sleep = sleep or time.sleep
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    agent = f"{getattr(settings, 'SITE_NAME', 'ShareBucketList')}/1.0 (+{getattr(settings, 'SITE_URL', '')})"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "User-Agent": agent,
                                                   "Accept": "application/json"})
    for attempt in range(RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt < RETRIES:
                retry = error.headers.get("Retry-After") if error.headers else None
                sleep(int(retry) if retry and retry.isdigit() else WAIT)
                continue
            if error.code == 403:
                raise ApiError("REST Countries refused the request (403): the monthly quota is used up, or the "
                               "account is frozen.") from None
            if error.code == 401:
                raise ApiError("REST Countries didn't accept the API key (401): check RESTCOUNTRIES_API_KEY.") from None
            if error.code == 404:
                return {"data": {"objects": []}}
            raise ApiError(f"REST Countries answered {error.code}.") from None
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise ApiError(f"REST Countries couldn't be reached: {error.__class__.__name__}.") from None
    raise ApiError("REST Countries kept answering 429 (too many requests).")


def _objects(payload):
    data = (payload or {}).get("data") or {}
    objects = data.get("objects") if isinstance(data, dict) else None
    if objects is None and isinstance(data, dict) and data.get("codes"):
        objects = [data]  # a single-country answer
    return list(objects or []), (data.get("meta") or {}) if isinstance(data, dict) else {}


def currencies(value):
    """[(code, name)] from their ``currencies`` object, whichever of the shapes it comes in."""
    found = []
    if isinstance(value, dict):
        if "code" in value:
            value = [value]
        else:
            for code, detail in value.items():
                name = detail.get("name", "") if isinstance(detail, dict) else str(detail or "")
                found.append((str(code).upper(), name))
            return found
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, dict) and entry.get("code"):
                found.append((str(entry["code"]).upper(), entry.get("name", "")))
            elif isinstance(entry, str):
                found.append((entry.upper(), ""))
    return found


def _plain(country):
    names, codes = country.get("names") or {}, country.get("codes") or {}
    return {
        "alpha_2": (codes.get("alpha_2") or "").upper(), "alpha_3": (codes.get("alpha_3") or "").upper(),
        "common": names.get("common") or "", "official": names.get("official") or "",
        "alternates": list(names.get("alternates") or []),
        "currencies": currencies(country.get("currencies")),
        "calling_codes": [str(c) for c in country.get("calling_codes") or []],
        "continents": [str(c) for c in country.get("continents") or []],
    }


def fetch(key, alpha_2=None, sleep=None):
    """Their countries as plain dicts (in memory only), every one or just ``alpha_2``'s."""
    if not key:
        raise ApiError("RESTCOUNTRIES_API_KEY isn't set.")
    if alpha_2:
        objects, _ = _objects(_get(f"/codes.alpha_2/{urllib.parse.quote(alpha_2.upper())}",
                                   {"response_fields": FIELDS}, key, sleep))
        return [_plain(c) for c in objects]
    found, offset = [], 0
    while True:
        objects, meta = _objects(_get("", {"response_fields": FIELDS, "limit": PAGE, "offset": offset}, key, sleep))
        found += [_plain(c) for c in objects]
        offset += len(objects)
        if not objects or not meta.get("more"):
            return found
