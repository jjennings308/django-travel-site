"""One search over the published catalogue (site roadmap R20).

``search(q, filters, user)`` returns results grouped by kind — areas (countries and regions), cities,
places, activities, events — each a ranked queryset. Ranking is Postgres full-text search over a
weighted vector (A name, B where it is, C its category or type, D its description), plus trigram word
similarity on the name for typos and short queries, plus a bonus for an exact or leading name match.
Accents are ignored on both sides (``unaccent`` on the columns, ``strip_accents`` on the query). Only
published items: approved places, public approved activities, events the reader may see (upcoming
unless ``past`` is asked for). Lives in ``pages`` because it reads every catalogue app.
"""
import unicodedata
from dataclasses import dataclass, field

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector, TrigramWordSimilarity
from django.db.models import Case, F, FloatField, Func, Q, TextField, Value, When
from django.db.models.functions import Lower
from django.utils import timezone

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event
from apps.locations.models import POI, City, Country, Region

CONFIG = "english"
SIMILAR = 0.45  # trigram word similarity that counts as a match (catches "Neuschwanstien")
SIMILAR_SHORT = 0.7  # for words under 5 letters, where a shared "rom" is noise ("rome" ≠ "Romania")
GROUP_SIZE = 8

#: kind -> heading, in page order. "area" is countries and regions together.
KINDS = {"area": "Countries & regions", "city": "Cities", "place": "Places", "activity": "Activities",
         "event": "Events"}
#: Kinds a filter applies to; choosing the filter leaves only these.
MONTH_KINDS = CATEGORY_KINDS = ("activity", "event")


def strip_accents(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _ua(expr):
    return Func(expr if hasattr(expr, "resolve_expression") else F(expr), function="unaccent",
                output_field=TextField())


def _vector(weighted):
    """SearchVector over (field, weight) pairs, each unaccented."""
    vector = None
    for name, weight in weighted:
        part = SearchVector(_ua(name), weight=weight, config=CONFIG)
        vector = part if vector is None else vector + part
    return vector


#: Per kind: the vector's fields by weight.
FIELDS = {
    Country: [("name", "A"), ("continent", "B"), ("description", "D")],
    Region: [("name", "A"), ("country__name", "B"), ("description", "D")],
    City: [("name", "A"), ("region__name", "B"), ("country__name", "B"), ("description", "D")],
    POI: [("name", "A"), ("city__name", "B"), ("city__region__name", "B"), ("city__country__name", "B"),
          ("poi_type__name", "C"), ("description", "D")],
    Activity: [("name", "A"), ("city__name", "B"), ("region__name", "B"), ("country__name", "B"),
               ("suggested_location", "B"), ("category__name", "C"), ("short_description", "D"),
               ("description", "D")],
    Event: [("name", "A"), ("city__name", "B"), ("country__name", "B"), ("location_text", "B"),
            ("venue_name", "B"), ("category__name", "C"), ("related_activity__name", "C"),
            ("short_description", "D"), ("description", "D")],
}


def ranked(queryset, q):
    """``queryset`` narrowed to matches of ``q`` and ordered best first (annotated ``score``)."""
    model = queryset.model
    plain = strip_accents(q).strip()
    query = SearchQuery(plain, search_type="websearch", config=CONFIG)
    lowered = plain.lower()
    return (queryset
            .annotate(search_vector=_vector(FIELDS[model]),
                      name_plain=Lower(_ua("name")),
                      similarity=TrigramWordSimilarity(Value(plain), Lower(_ua("name"))))
            .annotate(rank=SearchRank(F("search_vector"), query),
                      bonus=Case(When(name_plain=lowered, then=Value(2.0)),
                                 When(name_plain__startswith=lowered, then=Value(0.6)),
                                 default=Value(0.0), output_field=FloatField()))
            .filter(Q(search_vector=query) | Q(similarity__gte=SIMILAR if len(lowered) >= 5 else SIMILAR_SHORT)
                    | (Q(name_plain__contains=lowered) if len(lowered) >= 3 else Q(pk__in=[])))
            .annotate(score=F("rank") + F("similarity") + F("bonus"))
            .order_by("-score", "name"))


@dataclass
class Filters:
    kind: str = ""
    country: str = ""   # country slug
    month: int = 0      # 1-12
    category: str = ""  # activity category slug
    past: bool = False

    @classmethod
    def from_get(cls, get):
        kind = get.get("kind", "")
        month = get.get("month", "")
        return cls(kind=kind if kind in KINDS else "", country=get.get("country", "").strip(),
                   month=int(month) if month.isdigit() and 1 <= int(month) <= 12 else 0,
                   category=get.get("category", "").strip(), past=get.get("past") == "1")

    def kinds(self):
        """The kinds these filters leave, in page order."""
        kinds = list(KINDS)
        if self.month or self.category:
            kinds = [k for k in kinds if k in MONTH_KINDS]
        return [k for k in kinds if not self.kind or k == self.kind]


def _published(kind, user, filters):
    approved = {"approval_status": ApprovalStatus.APPROVED}
    country = filters.country
    if kind == "country":
        qs = Country.objects.filter(**approved)
        return qs.filter(slug=country) if country else qs
    if kind == "region":
        qs = Region.objects.filter(**approved).select_related("country")
        return qs.filter(country__slug=country) if country else qs
    if kind == "city":
        qs = City.objects.filter(**approved).select_related("region", "country")
        return qs.filter(country__slug=country) if country else qs
    if kind == "place":
        qs = POI.objects.filter(**approved).select_related("city__country", "poi_type")
        return qs.filter(city__country__slug=country) if country else qs
    if kind == "activity":
        qs = Activity.get_public_activities().select_related("category", "city", "region", "country",
                                                             *Activity.PICTURE_RELATED)
        if country:
            qs = qs.filter(country__slug=country)
        if filters.month:
            qs = qs.filter(usual_months__contains=[filters.month])
        if filters.category:
            qs = qs.filter(category__slug=filters.category)
        return qs
    if kind == "event":
        today = timezone.localdate()
        qs = Event.objects.visible_to(user).select_related("category", "city__country", "country",
                                                          *Event.PICTURE_RELATED)
        if not filters.past:
            qs = qs.filter(Q(end_date__gte=today) | Q(end_date__isnull=True, start_date__gte=today))
        if country:
            qs = qs.filter(Q(city__country__slug=country) | Q(country__slug=country))
        if filters.month:
            qs = qs.filter(start_date__month=filters.month)
        if filters.category:
            qs = qs.filter(category__slug=filters.category)
        return qs
    raise ValueError(kind)


def results(kind, q, user, filters):
    """Ranked matches of one kind; for "area", countries then regions as two querysets."""
    if kind == "area":
        return [ranked(_published("country", user, filters), q), ranked(_published("region", user, filters), q)]
    return [ranked(_published(kind, user, filters), q)]


def areas(objs):
    """Countries and regions together, best first, each tagged ``area_kind`` for the template."""
    for obj in objs:
        obj.area_kind = "country" if isinstance(obj, Country) else "region"
    return sorted(objs, key=lambda obj: -obj.score)


@dataclass
class Group:
    kind: str
    heading: str
    items: list = field(default_factory=list)
    more: bool = False


def grouped(q, user, filters, size=GROUP_SIZE):
    """Up to ``size`` results per kind (one query per model), and whether there are more."""
    groups = []
    for kind in filters.kinds():
        items = []
        for qs in results(kind, q, user, filters):
            items += list(qs[:size + 1])
        if kind == "area":
            items = areas(items)
        if items:
            groups.append(Group(kind, KINDS[kind], items[:size], len(items) > size))
    return groups


def filter_choices():
    """Countries and categories for the filter selects (two queries)."""
    return {
        "countries": Country.objects.filter(approval_status=ApprovalStatus.APPROVED).order_by("name")
        .only("name", "slug"),
        "categories": ActivityCategory.objects.filter(is_active=True).only("name", "slug"),
    }
