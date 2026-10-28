"""Booking-todos K1, step 2 of 3: every to-do's ``leg`` / ``stay`` / ``activity`` becomes a ``TaskLink``.

Reverse: each to-do's first link (legs, then stays, then activities, lowest id first) goes back into its
FK; any further links are dropped, since before K1 a to-do could point at one item only. Data only, so the
schema changes are their own migrations (0056, 0058): Postgres refuses index work after a data change in
one transaction (see bucketlists 0003–0005)."""
from django.db import migrations

FIELDS = (("leg", "transportleg"), ("stay", "lodging"), ("activity", "tripactivity"))


def _types(apps):
    ContentType = apps.get_model("contenttypes", "ContentType")
    return {field: ContentType.objects.get_or_create(app_label="trips", model=model)[0] for field, model in FIELDS}


def forwards(apps, schema_editor):
    BookingTask = apps.get_model("trips", "BookingTask")
    TaskLink = apps.get_model("trips", "TaskLink")
    types = _types(apps)
    links = []
    for task in BookingTask.objects.all().only("pk", "leg_id", "stay_id", "activity_id"):
        for field, _model in FIELDS:
            item_id = getattr(task, f"{field}_id")
            if item_id:
                links.append(TaskLink(task_id=task.pk, content_type=types[field], object_id=item_id))
    TaskLink.objects.bulk_create(links, ignore_conflicts=True)


def backwards(apps, schema_editor):
    BookingTask = apps.get_model("trips", "BookingTask")
    TaskLink = apps.get_model("trips", "TaskLink")
    types = _types(apps)
    for task in BookingTask.objects.filter(links__isnull=False).distinct():
        for field, _model in FIELDS:
            first = TaskLink.objects.filter(task=task, content_type=types[field]).order_by("pk").first()
            if first is not None:
                setattr(task, f"{field}_id", first.object_id)
                task.save(update_fields=[field])
                break
    TaskLink.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("trips", "0056_task_links"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
