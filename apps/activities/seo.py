"""An activity's page tags and schema.org JSON-LD (site roadmap R22): a ``TouristTrip`` (something to do,
not a dated event), with its place when it has one."""
from django.urls import reverse

from apps.core import seo


def activity_jsonld(activity):
    data = {"@context": "https://schema.org", "@type": "TouristTrip", "name": activity.name,
            "url": seo.absolute(reverse("activities:activity_detail", args=[activity.slug]))}
    description = seo.describe(activity.short_description, activity.description, limit=500)
    if description:
        data["description"] = description
    if activity.category_id:
        data["touristType"] = activity.category.name
    if activity.city_id or activity.country_id:
        data["itinerary"] = {"@type": "Place", "name": activity.place_name}
    image = seo.media_url(activity.display_media)
    if image:
        data["image"] = [image]
    return data


def activity_meta(activity):
    return seo.meta(title=activity.name,
                    description=seo.describe(activity.short_description, activity.description,
                                             f"{activity.name}{f' in {activity.place_name}' if activity.place_name else ''}."),
                    image=seo.media_url(activity.display_media), jsonld=activity_jsonld(activity))
