# Link each activity's free-text suggested_location ("Munich, Germany") to the
# catalogue: a unique city match sets city/region/country and clears the text;
# otherwise a country match sets just the country. Unmatched text is left alone.
# Separate from 0009 so the new columns' indexes exist before rows are updated.
from django.db import migrations


def link(apps, schema_editor):
    Activity = apps.get_model("activities", "Activity")
    City = apps.get_model("locations", "City")
    Country = apps.get_model("locations", "Country")
    for activity in Activity.objects.exclude(suggested_location="").filter(city__isnull=True, country__isnull=True):
        parts = [p.strip() for p in activity.suggested_location.split(",") if p.strip()]
        if not parts:
            continue
        cities = City.objects.filter(name__iexact=parts[0])
        if len(parts) > 1:
            cities = cities.filter(country__name__iexact=parts[-1])
        if cities.count() == 1:
            city = cities.get()
            activity.city_id, activity.region_id, activity.country_id = city.pk, city.region_id, city.country_id
            activity.suggested_location = ""
        else:
            country = Country.objects.filter(name__iexact=parts[-1]).first()
            if country is None:
                continue
            activity.country_id = country.pk
        activity.save(update_fields=["city", "region", "country", "suggested_location"])


def unlink(apps, schema_editor):
    Activity = apps.get_model("activities", "Activity")
    for activity in Activity.objects.filter(city__isnull=False, suggested_location="").select_related("city__country"):
        activity.suggested_location = f"{activity.city.name}, {activity.city.country.name}"
        activity.save(update_fields=["suggested_location"])


class Migration(migrations.Migration):

    dependencies = [
        ("activities", "0009_activity_location_recurrence"),
    ]

    operations = [
        migrations.RunPython(link, unlink),
    ]
