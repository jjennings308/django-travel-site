# Hand-written: bucket-list lifecycle (idea -> dated -> trip -> done).
#
# makemigrations proposed RemoveField(poi) before AddField(pois), which would
# drop every item's place. Instead, three migrations, each its own transaction
# (Postgres refuses ALTER TABLE / CREATE INDEX on a table with pending
# deferred-FK trigger events, and Django creates indexes at the *end* of a
# migration, after any RunPython in it):
#   0003 adds `pois` (temporary related_name), the end date and the trip link;
#   0004 copies each item's POI across and attaches the activity to event-only
#        items whose event is a date of one;
#   0005 drops `poi` and gives `pois` its real related_name.
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bucketlists", "0002_poi_categories_private_default"),
        ("locations", "0009_alter_poi_poi_type"),
        ("trips", "0014_tripgrant_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="bucketlistitem",
            name="pois",
            field=models.ManyToManyField(blank=True, db_table="bucket_list_item_pois", related_name="+", to="locations.poi"),
        ),
        migrations.AddField(
            model_name="bucketlistitem",
            name="target_end_date",
            field=models.DateField(blank=True, help_text="Last day of the planned dates (blank = a single day)", null=True),
        ),
        migrations.AddField(
            model_name="bucketlistitem",
            name="trip",
            field=models.ForeignKey(blank=True, help_text="Trip planned for this item", null=True,
                                    on_delete=django.db.models.deletion.SET_NULL, related_name="bucket_list_items", to="trips.trip"),
        ),
    ]
