# Hand-written: point Event.category at the shared activity categories.
#
# makemigrations proposed an AlterField of `category` to the new target, which would
# keep the old EventCategory ids in the column and reinterpret them as
# ActivityCategory ids (wrong rows, or an FK violation). Instead: add a new column,
# copy each event's category across by name, swap the columns, then drop
# EventCategory. The (city, category) index is dropped and re-created around the
# swap so migration state and the database agree.
#
# Split in two (0005 copies, 0006 swaps) so the data update and the ALTER TABLEs run in
# separate transactions: Postgres refuses to ALTER a table with pending deferred-FK
# trigger events from an UPDATE in the same transaction.
import django.db.models.deletion
from django.db import migrations, models


def copy_by_name(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    ActivityCategory = apps.get_model("activities", "ActivityCategory")
    shared = {c.name.lower(): c for c in ActivityCategory.objects.all()}
    fallback = shared.get("other")
    for event in Event.objects.select_related("category"):
        event.category_shared = shared.get(event.category.name.lower(), fallback)
        event.save(update_fields=["category_shared"])


def copy_back(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    EventCategory = apps.get_model("events", "EventCategory")
    for event in Event.objects.select_related("category_shared"):
        cat, _ = EventCategory.objects.get_or_create(
            name=event.category_shared.name, defaults={"slug": event.category_shared.slug}
        )
        event.category = cat
        event.save(update_fields=["category"])


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0004_event_unlisted_location"),
        ("activities", "0008_shared_categories"),
    ]

    operations = [
        migrations.RemoveIndex(model_name="event", name="events_city_id_10f9bc_idx"),
        migrations.AddField(
            model_name="event",
            name="category_shared",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="+", to="activities.activitycategory",
            ),
        ),
        migrations.RunPython(copy_by_name, copy_back),
    ]
