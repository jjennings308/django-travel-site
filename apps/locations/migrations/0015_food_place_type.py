"""A "Food & drink" place type (site roadmap R18), so notable restaurants, markets and bakeries can be
catalogue places a trip's meals link to. get_or_create on the code: a type already added in the admin
as ``food`` is left as it is."""
from django.db import migrations


def add_food(apps, schema_editor):
    PlaceType = apps.get_model("locations", "PlaceType")
    shopping = PlaceType.objects.filter(code="shopping").values_list("sort_order", flat=True).first()
    PlaceType.objects.get_or_create(code="food", defaults={
        "name": "Food & drink", "icon": "bi-cup-hot", "sort_order": (shopping or 0) + 1})


def remove_food(apps, schema_editor):
    PlaceType = apps.get_model("locations", "PlaceType")
    POI = apps.get_model("locations", "POI")
    if not POI.objects.filter(poi_type="food").exists():
        PlaceType.objects.filter(code="food").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("locations", "0014_poi_trip_count"),
    ]

    operations = [
        migrations.RunPython(add_food, remove_food),
    ]
