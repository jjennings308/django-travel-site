"""Country, region, city and place page tags and schema.org JSON-LD (site roadmap R22)."""
from django.urls import reverse

from apps.core import seo

TYPES = {"country": "Country", "region": "AdministrativeArea", "city": "City", "place": "TouristAttraction"}
URLS = {"country": "locations:country_detail", "region": "locations:region_detail",
        "city": "locations:city_detail", "place": "locations:poi_detail"}


def _where(kind, obj):
    if kind == "place":
        return ", ".join(x for x in (obj.city.name, obj.city.country.name) if x)
    if kind == "city":
        return ", ".join(x.name for x in (obj.region, obj.country) if x)
    if kind == "region":
        return obj.country.name
    return obj.continent or ""


def place_jsonld(kind, obj):
    data = {"@context": "https://schema.org", "@type": TYPES[kind], "name": obj.name,
            "url": seo.absolute(reverse(URLS[kind], args=[obj.slug]))}
    description = seo.describe(getattr(obj, "description", ""), limit=500)
    if description:
        data["description"] = description
    if getattr(obj, "latitude", None) is not None and getattr(obj, "longitude", None) is not None:
        data["geo"] = {"@type": "GeoCoordinates", "latitude": float(obj.latitude), "longitude": float(obj.longitude)}
    if kind == "place":
        data["address"] = {"@type": "PostalAddress", "addressLocality": obj.city.name,
                           "addressCountry": obj.city.country.iso_code}
        if obj.address:
            data["address"]["streetAddress"] = obj.address
    elif kind in ("city", "region"):
        data["containedInPlace"] = {"@type": "Country", "name": obj.country.name}
    image = seo.media_url(obj.featured_media)
    if image:
        data["image"] = [image]
    return data


def place_meta(kind, obj):
    where = _where(kind, obj)
    title = f"{obj.name}, {where}" if where and kind != "country" else obj.name
    return seo.meta(title=title,
                    description=seo.describe(getattr(obj, "description", ""), f"{obj.name}{f', {where}' if where else ''}: "
                                             "things to do, places and events."),
                    image=seo.media_url(obj.featured_media), jsonld=place_jsonld(kind, obj))
