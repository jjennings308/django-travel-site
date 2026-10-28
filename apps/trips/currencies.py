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


def _cache(trip):
    cache = getattr(trip, "_currency_cache", None)
    if cache is None:
        from apps.locations.models import City, Country
        countries = dict(Country.objects.exclude(currency_code="").values_list("pk", "currency_code"))
        city_ids = [*trip.cities.values_list("pk", flat=True),
                    *trip.days.exclude(city=None).order_by("day_number").values_list("city_id", flat=True)]
        city_country = dict(City.objects.filter(pk__in=set(city_ids)).values_list("pk", "country_id"))
        trip_codes = [countries.get(city_country.get(pk)) for pk in city_ids]
        cache = {"countries": countries, "cities": city_country,
                 "trip": list(dict.fromkeys(code.upper() for code in trip_codes if code))}
        trip._currency_cache = cache
    return cache


def _city_code(trip, city_id):
    cache = _cache(trip)
    if city_id not in cache["cities"]:  # a city outside the trip's (a leg's far end): one lookup, kept
        from apps.locations.models import City
        cache["cities"][city_id] = City.objects.filter(pk=city_id).values_list("country_id", flat=True).first()
    code = cache["countries"].get(cache["cities"][city_id])
    return code.upper() if code else None


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


def setup(form, name, trip, city_ids=(), given_initial=False, codes=None):
    """Turn ``form.fields[name]`` into a currency select for ``trip`` and, on a new item that wasn't
    given a currency, start it on ``default_for``. ``codes`` overrides the list (exchange rates)."""
    model_field = form._meta.model._meta.get_field(name)
    required = not model_field.blank
    old = form.fields[name]
    form.fields[name] = CurrencyField(
        required=required, label=old.label, help_text=old.help_text,
        # Exchange-rate rows start blank so a formset's untouched extra row isn't "changed".
        widget=CurrencySelect(codes if codes is not None else choices_for(trip, city_ids),
                              allow_blank=not required or codes is not None, styled=False))
    if form.instance.pk is None and not given_initial and codes is None:
        form.initial[name] = default_for(trip, city_ids)
