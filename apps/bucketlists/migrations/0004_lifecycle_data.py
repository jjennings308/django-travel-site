# Data step of the bucket-list lifecycle change; see 0003_lifecycle.
from django.db import migrations


def forwards(apps, schema_editor):
    Item = apps.get_model("bucketlists", "BucketListItem")
    for item in Item.objects.filter(poi__isnull=False):
        item.pois.add(item.poi_id)
    for item in Item.objects.filter(activity__isnull=True, city__isnull=True,
                                    event__related_activity__isnull=False).select_related("event"):
        item.activity_id = item.event.related_activity_id
        item.save(update_fields=["activity"])


def backwards(apps, schema_editor):
    Item = apps.get_model("bucketlists", "BucketListItem")
    for item in Item.objects.filter(pois__isnull=False).distinct():
        item.poi_id = item.pois.order_by("pk").values_list("pk", flat=True).first()
        item.save(update_fields=["poi"])
    # An activity item that also has an event goes back to being an event item.
    Item.objects.filter(activity__isnull=False, event__isnull=False).update(activity=None)


class Migration(migrations.Migration):

    dependencies = [
        ("bucketlists", "0003_lifecycle"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
