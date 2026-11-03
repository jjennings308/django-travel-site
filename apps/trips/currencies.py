"""Currency choices on a trip's forms (edit-by-day plan E4).

Every currency field on a trip's forms offers the trip's **home currency** first, then the local
currencies of the places the item involves (``Country.currency_code``), deduplicated, plus Other… (a
typed three-letter code; ``apps.core.widgets.CurrencySelect``):

======================  =========================================================
Field                   Local currency from
======================  =========================================================
``Lodging``             its city's country, else the trip's countries
``TransportLeg``        its origin and destination cities' countries
``TripActivity``        its catalogue place's city, else the day's city
``Confirmation``        the places of the items it covers, else the trip's
``TripExpense``         its day's city, else the trip's countries
``TripRate`` from / to  every currency used on the trip, plus home
======================  =========================================================

"The trip's countries" are those of ``Trip.cities`` and the days' cities. The country codes and the
trip's cities are loaded once per page and cached on the trip object, so a formset doesn't query per
row. A new row starts on the item's local currency when there is exactly one, else on home.

**A cost always has a currency** (blank-currencies plan, CU1): where none was stored, ``currency_of`` reads it as
its place's local currency — never the reader's or the page's — and the day's notes, the Budget page, choices and
the booklet all ask it; an edit form starts such an item on it, and ``manage.py fill_currencies`` stores it.
"""
from django import forms

from apps.core.widgets import CurrencySelect


class CurrencyField(forms.CharField):
    """A three-letter code, uppercased; blank only where the model allows it."""

    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 3)
        super().__init__(**kwargs)

    def clean(self, value):
        value = (super().clean(value) or "").strip().upper()
        if value and (len(value) != 3 or not value.isalpha()):
            raise forms.ValidationError("Use a three-letter currency code, e.g. USD or EUR.", code="invalid")
        return value


def _cached(obj, name):
    """``obj.<name>`` when it's already loaded (select_related, or set by the page), else None: never a query."""
    if obj is None:
        return None
    return getattr(obj, name) if obj._meta.get_field(name).is_cached(obj) else None


def _code_from(city):
    """A loaded city's local currency when its country came with it (the trip page's joins), else None."""
    country = _cached(city, "country")
    return (country.currency_code or "").upper() or None if country is not None else None


def _cache(trip):
    """The trip's days, the local currency of each of the trip's cities (its own and its days') and the trip's
    codes in day order. No query when the cities came with their countries (the trip page's prefetch); one for
    the countries otherwise (plus the trip's cities and days when they weren't prefetched)."""
    cache = getattr(trip, "_currency_cache", None)
    if cache is None:
        from apps.locations.models import City
        all_days = list(trip.days.all())
        days = sorted((day for day in all_days if day.city_id), key=lambda day: (day.day_number, day.pk))
        cities = list(trip.cities.all()) + [_cached(day, "city") or day.city_id for day in days]
        codes, missing = {}, set()
        for city in cities:
            pk = city if isinstance(city, int) else city.pk
            code = None if isinstance(city, int) else _code_from(city)
            if code is not None or (not isinstance(city, int) and _cached(city, "country") is not None):
                codes[pk] = code
            else:
                missing.add(pk)
        missing -= set(codes)
        if missing:
            codes.update({pk: (code or "").upper() or None for pk, code in
                          City.objects.filter(pk__in=missing).values_list("pk", "country__currency_code")})
        order = [city if isinstance(city, int) else city.pk for city in cities]
        cache = {"codes": codes, "days": all_days,
                 "trip": list(dict.fromkeys(codes[pk] for pk in order if codes.get(pk)))}
        trip._currency_cache = cache
    return cache


def _city_code(trip, city_id, city=None):
    codes = _cache(trip)["codes"]
    if city_id not in codes:
        if city is not None and _cached(city, "country") is not None:
            codes[city_id] = _code_from(city)
        else:  # a city outside the trip's (a leg's far end): one lookup, kept
            from apps.locations.models import City
            code = City.objects.filter(pk=city_id).values_list("country__currency_code", flat=True).first()
            codes[city_id] = (code or "").upper() or None
    return codes[city_id]


def local_codes(trip, city_ids=()):
    """The local currencies of these cities, else of the trip's countries."""
    codes = [_city_code(trip, pk) for pk in city_ids if pk]
    return list(dict.fromkeys(code for code in codes if code)) or list(_cache(trip)["trip"])


def choices_for(trip, city_ids=()):
    return list(dict.fromkeys(code for code in (trip.home_currency, *local_codes(trip, city_ids)) if code))


def default_for(trip, city_ids=()):
    """A new item's currency: the one local currency, else the trip's home currency."""
    codes = local_codes(trip, city_ids)
    return codes[0] if len(codes) == 1 else (trip.home_currency or "USD")


def used_codes(trip):
    """Every currency the trip's costs use (for its own exchange rates), home first."""
    codes = [trip.home_currency]
    for manager in (trip.expenses, trip.lodging, trip.transport, trip.activities, trip.confirmations):
        codes += manager.exclude(currency="").values_list("currency", flat=True).distinct()
    return list(dict.fromkeys(code.upper() for code in codes if code))


def activity_city_ids(activity):
    if activity.poi_id:
        from apps.locations.models import POI
        return [POI.objects.filter(pk=activity.poi_id).values_list("city_id", flat=True).first()]
    return [activity.day.city_id] if activity.day_id else []


def confirmation_city_ids(confirmation):
    """The places of the items a confirmation covers."""
    if not confirmation.pk:
        return []
    ids = []
    for link in confirmation.links.select_related("content_type"):
        item = link.content_type.get_object_for_this_type(pk=link.object_id) if link.content_type_id else None
        if item is None:
            continue
        if hasattr(item, "origin_city_id"):
            ids += [item.origin_city_id, item.destination_city_id]
        elif hasattr(item, "check_in"):
            ids.append(item.city_id)
        elif hasattr(item, "poi_id") and hasattr(item, "kind"):
            ids += activity_city_ids(item)
        elif hasattr(item, "day_id"):
            ids.append(item.day.city_id)
    return ids


# ---- a cost with no currency takes its place's (blank-currencies plan, CU1) -------------------------------------

def place_cities(item):
    """[(city or None, city id)] of an item's own place: a leg's origin, a stay's city, the catalogue place (else
    event venue, else activity) of an activity, meal, section or choice option, an option's city. The city object
    only when it's loaded already (so its country may be too); never a query over the trip page's prefetch."""
    name = type(item).__name__

    def of(owner, field):
        pk = getattr(owner, f"{field}_id", None)
        return [(_cached(owner, field), pk)] if pk else []
    if name == "TransportLeg":
        return of(item, "origin_city")
    if name == "Lodging":
        return of(item, "city")
    if name == "Option" and item.city_id:
        return of(item, "city")
    if getattr(item, "poi_id", None):
        return of(item.poi, "city")
    if getattr(item, "event_id", None):
        event = item.event
        return of(event.poi, "city") if event.poi_id else of(event, "city")
    if getattr(item, "activity_id", None):
        return of(item.activity, "city")
    return []


def _day_of(item, trip):
    name = type(item).__name__
    days = _cache(trip)["days"]
    if name == "TransportLeg":
        on_day = getattr(item, "on_day", None)
        return on_day or next((day for day in days if day.date and day.date == item.date), None)
    if name == "Lodging":
        return next((day for day in days if day.date and day.date == item.check_in), None)
    if name == "Option":
        return next((day for day in days if day.pk == item.group.day_id), None)
    day_id = getattr(item, "day_id", None)
    return next((day for day in days if day.pk == day_id), None)


def currency_of(item, trip, day=None):
    """The currency an item's cost is in: the stored code, else its place's (``place_currency``). Never the
    reader's. No queries over the trip page's prefetch (its cities come with their countries)."""
    stored = (getattr(item, "currency", "") or "").strip().upper()
    if stored or trip is None:
        return stored
    return place_currency(item, trip, day)


def place_currency(item, trip, day=None):
    """The local currency of an item's place: a trip activity's catalogue place's own entry-fee currency first,
    then the place's city (``place_cities``), then its day's city, else ``default_for`` (the trip's one local
    currency, else home). A confirmation's: the places of the items it covers when they agree, else
    ``default_for``."""
    return place_source(item, trip, day)[0]


def place_source(item, trip, day=None):
    """``place_currency`` and where it came from: (code, ("fee", poi) / ("city", city id) / ("covers", None) /
    ("trip", None)) — ``fill_currencies`` names it."""
    name = type(item).__name__
    if name == "Confirmation":
        codes = {place_currency(covered, trip) for covered in item.covered_items()}
        return (codes.pop(), ("covers", None)) if len(codes) == 1 else (default_for(trip), ("trip", None))
    if name == "TripActivity" and item.poi_id and item.poi.entry_fee_currency:
        return item.poi.entry_fee_currency.upper(), ("fee", item.poi)
    if day is None:
        day = _day_of(item, trip)
    for cities in (place_cities(item), [(_cached(day, "city"), day.city_id)] if day is not None and day.city_id else []):
        for city, pk in cities:
            code = _city_code(trip, pk, city)
            if code:
                return code, ("city", pk)
    return default_for(trip), ("trip", None)


def day_of(item, trip):
    """The trip day an item is on (a stay: its check-in day; a leg: its date's; an option: its choice's)."""
    return _day_of(item, trip)


def setup(form, name, trip, city_ids=(), given_initial=False, codes=None):
    """Turn ``form.fields[name]`` into a currency select for ``trip`` and, on a new item that wasn't
    given a currency, start it on ``default_for``; an existing one with no currency stored starts on its place's
    (``currency_of``, CU1), so an edit never quietly suggests home. ``codes`` overrides the list (exchange rates)."""
    model_field = form._meta.model._meta.get_field(name)
    required = not model_field.blank
    old = form.fields[name]
    form.fields[name] = CurrencyField(
        required=required, label=old.label, help_text=old.help_text,
        # Exchange-rate rows start blank so a formset's untouched extra row isn't "changed".
        widget=CurrencySelect(codes if codes is not None else choices_for(trip, city_ids),
                              allow_blank=not required or codes is not None, styled=False))
    if given_initial or codes is not None:
        return
    if form.instance.pk is None:
        form.initial[name] = default_for(trip, city_ids)
    elif not (getattr(form.instance, name, "") or "") and name == "currency":
        if type(form.instance).__name__ == "Option":  # a formset row: the places its page already gave
            codes = [code for code in (_city_code(trip, pk) for pk in city_ids if pk) if code]
            form.initial[name] = codes[0] if codes else default_for(trip, city_ids)
        else:
            form.initial[name] = currency_of(form.instance, trip)


# ---- filling the stored blanks once (CU1: ``manage.py fill_currencies``) -------------------------------------

#: The models with a cost and a currency, and their amount field.
COSTED = (("TransportLeg", "cost"), ("Lodging", "nightly_rate"), ("TripActivity", "est_cost"), ("Meal", "est_cost"),
          ("Option", "est_cost"), ("Confirmation", "cost"))


def _blank_items(trip):
    from . import models
    found = []
    for name, amount in COSTED:
        model = getattr(models, name)
        trip_path = {"Meal": "day__trip", "Option": "group__trip"}.get(name, "trip")
        queryset = model.objects.filter(**{trip_path: trip, f"{amount}__isnull": False, "currency": ""})
        if name == "Option":
            queryset = queryset.select_related("group")
        found += list(queryset.order_by("pk"))
    return found


def _item_label(item):
    from .booking_tasks import label
    name = type(item).__name__
    if name == "Meal":
        return item.name
    if name == "Option":
        return f"{item.group.prompt}: {item.title}"
    if name == "Confirmation":
        return f"Booking {item.confirmation_number}"
    return label(item)


def blanks(trip):
    """Every leg, stay, activity, meal, choice option and confirmation of ``trip`` with an amount and no currency,
    with the code ``currency_of`` reads it as: [{"item", "label", "day", "code", "why"}], "why" being "from
    Schwangau", "Hohenschwangau Castle's entry fee", "from what it covers" or "the trip's currency". Items with
    no amount are left alone."""
    from apps.locations.models import City
    rows = []
    for item in _blank_items(trip):
        code, (kind, what) = place_source(item, trip)
        if kind == "fee":
            why = f"{what.name}'s entry fee"
        elif kind == "city":
            why = f"from {City.objects.filter(pk=what).values_list('name', flat=True).first() or 'its city'}"
        elif kind == "covers":
            why = "from what it covers"
        else:
            why = "the trip's currency"
        day = None if type(item).__name__ == "Confirmation" else _day_of(item, trip)
        rows.append({"item": item, "label": _item_label(item), "day": day, "code": code, "why": why})
    return rows


def fill(trip, rows, actor=None):
    """Store each row's code (one transaction, no other field touched) under one history line: "Filled in 6
    missing currencies". Returns how many were filled."""
    from django.db import transaction
    from . import changes
    from .models import TripChange
    rows = [row for row in rows if row["code"]]
    if not rows:
        return 0
    with transaction.atomic():
        for row in rows:
            item = row["item"]
            type(item).objects.filter(pk=item.pk, currency="").update(currency=row["code"])
        noun = "currency" if len(rows) == 1 else "currencies"
        changes.record(trip.pk, TripChange.Kind.CHANGED, f"Filled in {len(rows)} missing {noun}", item=trip,
                       actor=actor)
    return len(rows)


def fee_offer(activity, trip):
    """A trip activity linked to a catalogue place with an entry fee and no estimate of its own is offered that fee
    (CU1), never given it silently: {"amount", "currency", "text": "Use Hohenschwangau Castle's entry fee: €21 per
    person"}, else None. The currency is the place's own fee currency, else its city's."""
    from .costs import money
    poi = activity.poi if activity is not None and activity.poi_id else None
    if poi is None or poi.entry_fee is None or activity.est_cost is not None:
        return None
    code = (poi.entry_fee_currency or "").upper() or _city_code(trip, poi.city_id) or default_for(trip)
    return {"amount": poi.entry_fee, "currency": code,
            "text": f"Use {poi.name}'s entry fee: {money(poi.entry_fee, code)} per person"}
