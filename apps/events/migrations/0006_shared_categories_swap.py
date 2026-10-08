# Second half of the shared-category switch (see 0005): swap the copied column into
# place, restore the (city, category) index and drop EventCategory.
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0005_shared_categories"),
    ]

    operations = [
        migrations.RemoveField(model_name="event", name="category"),
        migrations.RenameField(model_name="event", old_name="category_shared", new_name="category"),
        migrations.AlterField(
            model_name="event",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="events", to="activities.activitycategory",
            ),
        ),
        migrations.AddIndex(
            model_name="event",
            index=models.Index(fields=["city", "category"], name="events_city_id_10f9bc_idx"),
        ),
        migrations.DeleteModel(name="EventCategory"),
    ]
