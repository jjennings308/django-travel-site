"""Retire decision to-dos (retire-decision-todos D2), step 1 of 2: before ``TaskOption`` goes (0055), each
to-do's options are written into its notes — "Options considered: A; B (chosen); C" — so nothing is lost.
Refuses while an open to-do still has options: those belong in a "choose one" on their day, which D1's
``convert_day_first --all --apply`` did (that command is gone now; run D1's code first). Data only, so the
schema change is its own migration (Postgres won't alter a table with pending trigger events)."""
from django.db import migrations


def options_into_notes(apps, schema_editor):
    BookingTask = apps.get_model("trips", "BookingTask")
    TaskOption = apps.get_model("trips", "TaskOption")
    open_ids = sorted(set(TaskOption.objects.filter(task__done=False).values_list("task__trip_id", flat=True)))
    if open_ids:
        raise RuntimeError("Open to-dos still have options: run `manage.py convert_day_first --all --apply` (on the "
                           "D1 code) first. Trips: " + ", ".join(str(pk) for pk in open_ids))
    for task in BookingTask.objects.filter(options__isnull=False).distinct():
        titles = [o.title + (" (chosen)" if o.chosen else "") for o in TaskOption.objects.filter(task=task).order_by("order", "id")]
        line = "Options considered: " + "; ".join(titles)
        task.notes = "\n".join(p for p in (task.notes, line) if p)
        task.save(update_fields=["notes"])


class Migration(migrations.Migration):

    dependencies = [
        ("trips", "0053_cover_photo"),
    ]

    operations = [
        migrations.RunPython(options_into_notes, migrations.RunPython.noop),
    ]
