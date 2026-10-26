"""The "Catalogue notes" approval queue, so members' notes appear on /approval/ (as events 0003 did)."""
from django.db import migrations


def seed(apps, schema_editor):
    ApprovalQueue = apps.get_model("approval_system", "ApprovalQueue")
    ContentType = apps.get_model("contenttypes", "ContentType")
    queue, _ = ApprovalQueue.objects.get_or_create(
        slug="catalogue-notes",
        defaults={"name": "Catalogue notes", "description": "Notes members add to places, activities and events",
                  "status_filter": "pending", "icon": "📝"},
    )
    ct, _ = ContentType.objects.get_or_create(app_label="catalogue_notes", model="cataloguenote")
    queue.content_types.add(ct)


def unseed(apps, schema_editor):
    apps.get_model("approval_system", "ApprovalQueue").objects.filter(slug="catalogue-notes").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("catalogue_notes", "0001_initial"),
        ("approval_system", "0001_initial"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
