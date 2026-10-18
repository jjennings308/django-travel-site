# Seed the trip notification kinds added by the site roadmap (services.KINDS): R1's invite
# accepted (until now created on first use) and R7's trip changed.
from django.db import migrations

CATEGORY = "Activity on your account"
KINDS = {
    "trip_invite_accepted": ("Someone accepted your trip invitation",
                             "Someone you invited joined a trip."),
    "trip_changed": ("A trip you're on changed",
                     "The daily list of changes to a trip, and journey time changes in the week before travel."),
}


def seed(apps, schema_editor):
    Category = apps.get_model("notifications", "NotificationCategory")
    Type = apps.get_model("notifications", "NotificationType")
    category, _ = Category.objects.get_or_create(name=CATEGORY, defaults={"icon": "bi-bell"})
    for name, (display, description) in KINDS.items():
        Type.objects.update_or_create(name=name, defaults={
            "category": category, "display_name": display, "description": description,
            "default_email": True, "default_in_app": True, "default_push": False, "is_system": True})


def unseed(apps, schema_editor):
    apps.get_model("notifications", "NotificationType").objects.filter(name="trip_changed").delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0002_seed_types")]
    operations = [migrations.RunPython(seed, unseed)]
