"""Retire decision to-dos (retire-decision-todos D2), step 2 of 2: ``TaskOption`` (with its
``taskoption_one_chosen`` index) and ``BookingTask.kind`` go; every to-do is a booking to-do. 0054 wrote
the options into the to-dos' notes first."""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("trips", "0054_task_options_into_notes"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="taskoption",
            name="taskoption_one_chosen",
        ),
        migrations.RemoveField(
            model_name="bookingtask",
            name="kind",
        ),
        migrations.DeleteModel(
            name="TaskOption",
        ),
    ]
