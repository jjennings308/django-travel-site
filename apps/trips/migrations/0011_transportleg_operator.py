# Hand-written, deliberately. `makemigrations` proposes RemoveField + AddField
# here, because the new fields carry `help_text` and so are not "identical" to
# the ones they replace — it cannot pair them as a rename. Applying that would
# drop the operator and service number of every existing leg on the floor.
# `RenameField` renames the column and keeps the rows, and the two AlterFields
# then add the help_text that cost the autodetector the pairing.
#
# This is the same trap as `0006`, where the same autodetector proposed deleting
# `Flight` and creating `TransportLeg` and would have dropped four legs.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("trips", "0010_trip_public_token"),
    ]

    operations = [
        migrations.RenameField(
            model_name="transportleg",
            old_name="airline",
            new_name="operator",
        ),
        migrations.RenameField(
            model_name="transportleg",
            old_name="flight_number",
            new_name="service_number",
        ),
        migrations.AlterField(
            model_name="transportleg",
            name="operator",
            field=models.CharField(
                blank=True,
                help_text="Airline, rail company, or hire company — whatever carries you",
                max_length=120,
            ),
        ),
        migrations.AlterField(
            model_name="transportleg",
            name="service_number",
            field=models.CharField(
                blank=True,
                help_text="Flight number, train service number, or booking reference",
                max_length=20,
            ),
        ),
    ]
