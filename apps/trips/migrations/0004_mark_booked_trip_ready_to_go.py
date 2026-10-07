"""Set the fully-booked Taos trip to ``ready_to_go``.

The ``status`` field defaults to ``starting``, which is right for a trip being
planned but wrong for the one trip that already has every flight, hotel, car
and confirmation booked and imported. Left alone it would read as "barely
started", and Taos is the reference example of a finished itinerary.

Matched on name plus both dates rather than on primary key, because the row's
pk differs between this machine and the production box — the data is identical
but the sequence is not. A reverse is provided for symmetry and puts the trip
back to the field default; it is only correct if the trip genuinely was not
finished, which is why this is a data migration and not a schema one.
"""

from django.db import migrations

TRIP_NAME = "James & Regan — Taos / Angel Fire, New Mexico"
START_DATE = "2026-09-12"
END_DATE = "2026-09-19"


def mark_ready(apps, schema_editor):
    Trip = apps.get_model("trips", "Trip")
    Trip.objects.filter(
        name=TRIP_NAME,
        start_date=START_DATE,
        end_date=END_DATE,
    ).update(status="ready_to_go")


def unmark_ready(apps, schema_editor):
    Trip = apps.get_model("trips", "Trip")
    Trip.objects.filter(
        name=TRIP_NAME,
        start_date=START_DATE,
        end_date=END_DATE,
    ).update(status="starting")


class Migration(migrations.Migration):

    dependencies = [
        ("trips", "0003_trip_status_bookingtask"),
    ]

    operations = [
        migrations.RunPython(mark_ready, unmark_ready),
    ]
