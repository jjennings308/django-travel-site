# Last step of 0003: drop the single `poi` FK now that `pois` holds it.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bucketlists", "0004_lifecycle_data"),
    ]

    operations = [
        migrations.RemoveField(model_name="bucketlistitem", name="poi"),
        migrations.AlterField(
            model_name="bucketlistitem",
            name="pois",
            field=models.ManyToManyField(blank=True, db_table="bucket_list_item_pois",
                                         help_text="Places / points of interest to visit (one item can cover several)",
                                         related_name="bucket_list_items", to="locations.poi"),
        ),
    ]
