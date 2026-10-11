# Seed the notification category and the four kinds the site sends (services.KINDS).
from django.db import migrations

CATEGORY = "Activity on your account"
KINDS = {
    "submission_reviewed": ("Your submission was reviewed", "Your event, activity or place was approved, rejected or needs changes."),
    "submission_received": ("New submission to review", "Staff: someone submitted something for review."),
    "role_request_decided": ("Your role request was decided", "Your vendor or content-provider request was approved or rejected."),
    "trip_access_granted": ("You were added to a trip", "Someone gave you access to a trip."),
}


def seed(apps, schema_editor):
    Category = apps.get_model("notifications", "NotificationCategory")
    Type = apps.get_model("notifications", "NotificationType")
    category, _ = Category.objects.get_or_create(name=CATEGORY, defaults={"icon": "bi-bell"})
    for name, (display, description) in KINDS.items():
        Type.objects.get_or_create(name=name, defaults={
            "category": category, "display_name": display, "description": description,
            "default_email": True, "default_in_app": True, "default_push": False, "is_system": True})


def unseed(apps, schema_editor):
    apps.get_model("notifications", "NotificationType").objects.filter(name__in=KINDS).delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
