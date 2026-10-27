"""Find a city by typing (day-first plan, P1): the type-to-search box on the trips forms
(``widgets.CitySearchInput``) and ``locations:city_search``.

Ranked like the site search (``pages.search``, which this layer may not import): accents ignored on
both sides (``unaccent`` on the name, ``strip_accents`` on the query), a trigram word similarity on the
name, a bonus for an exact (2.0) or leading (0.6) name and a substring match from 3 letters. Approved
cities, plus the member's own pending submissions (so a city they just added is usable at once).
"""
import unicodedata

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db.models import Case, F, FloatField, Func, Q, TextField, Value, When
from django.db.models.functions import Lower

from apps.approval_system.models import ApprovalStatus

from .models import City

LIMIT = 10
SIMILAR = 0.45
SIMILAR_SHORT = 0.7  # under 5 letters a loose trigram match is mostly noise


def strip_accents(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _ua(expr):
    return Func(F(expr), function="unaccent", output_field=TextField())


def visible_cities(user):
    """Approved cities, plus ``user``'s own pending ones."""
    q = Q(approval_status=ApprovalStatus.APPROVED)
    if user is not None and user.is_authenticated:
        q |= Q(submitted_by=user, approval_status=ApprovalStatus.PENDING)
    return City.objects.filter(q)


def search(q, user, country=None, limit=LIMIT):
    """Up to ``limit`` cities matching ``q``, best first. ``country``: an ISO code or a pk."""
    plain = strip_accents(q or "").strip().lower()
    if not plain:
        return []
    cities = visible_cities(user).select_related("region", "country")
    if country:
        cities = cities.filter(Q(country__iso_code__iexact=country) if not str(country).isdigit()
                               else Q(country_id=country))
    return list(
        cities.annotate(name_plain=Lower(_ua("name")),
                        similarity=TrigramWordSimilarity(Value(plain), Lower(_ua("name"))),
                        bonus=Case(When(name_plain=plain, then=Value(2.0)),
                                   When(name_plain__startswith=plain, then=Value(0.6)),
                                   default=Value(0.0), output_field=FloatField()))
        .filter(Q(similarity__gte=SIMILAR if len(plain) >= 5 else SIMILAR_SHORT)
                | (Q(name_plain__contains=plain) if len(plain) >= 3 else Q(name_plain__startswith=plain)))
        .annotate(score=F("similarity") + F("bonus"))
        .order_by("-score", "-visitor_count", "name")[:limit])


def as_json(city):
    """What the search box shows and needs for a city."""
    return {
        "id": city.pk,
        "name": city.name,
        "label": str(city),
        "region": city.region.name if city.region_id else "",
        "country": city.country.name,
        "flag": city.country.flag,
        "timezone": city.timezone,
        "lat": float(city.latitude) if city.latitude is not None else None,
        "lng": float(city.longitude) if city.longitude is not None else None,
        "pending": city.approval_status != ApprovalStatus.APPROVED,
    }
