# Seed R15's notification kind: staff hear when a catalogue item is reported (admin_tools.reports).
from django.db import migrations

CATEGORY = "Activity on your account"


def seed(apps, schema_editor):
    Category = apps.get_model("notifications", "NotificationCategory")
    Type = apps.get_model("notifications", "NotificationType")
    category, _ = Category.objects.get_or_create(name=CATEGORY, defaults={"icon": "bi-bell"})
    Type.objects.update_or_create(name="content_reported", defaults={
        "category": category, "display_name": "Something in the catalogue was reported",
        "description": "Staff: a member reported an activity, event or place.",
        "default_email": True, "default_in_app": True, "default_push": False, "is_system": True})


def unseed(apps, schema_editor):
    apps.get_model("notifications", "NotificationType").objects.filter(name="content_reported").delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0003_seed_trip_kinds")]
    operations = [migrations.RunPython(seed, unseed)]
