# Seed R17's notification kind: "How was <trip>?" after a trip ends (trips.ratings).
from django.db import migrations

CATEGORY = "Activity on your account"


def seed(apps, schema_editor):
    Category = apps.get_model("notifications", "NotificationCategory")
    Type = apps.get_model("notifications", "NotificationType")
    category, _ = Category.objects.get_or_create(name=CATEGORY, defaults={"icon": "bi-bell"})
    Type.objects.update_or_create(name="trip_rating", defaults={
        "category": category, "display_name": "Rate a finished trip",
        "description": "After a trip ends: rate the places you went.",
        "default_email": True, "default_in_app": True, "default_push": False, "is_system": True})


def unseed(apps, schema_editor):
    apps.get_model("notifications", "NotificationType").objects.filter(name="trip_rating").delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0004_seed_content_reported")]
    operations = [migrations.RunPython(seed, unseed)]
