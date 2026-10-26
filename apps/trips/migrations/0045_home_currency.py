"""Trip.home_currency (edit-by-day plan E4): added as USD, then each trip takes its creator's preferred
currency (Settings) when they have one. Reversing drops the column."""
from django.db import migrations, models


def from_creators(apps, schema_editor):
    Trip = apps.get_model("trips", "Trip")
    AccountSettings = apps.get_model("accounts", "AccountSettings")
    preferred = dict(AccountSettings.objects.exclude(preferred_currency="").values_list("user_id", "preferred_currency"))
    for trip in Trip.objects.exclude(created_by=None).only("pk", "created_by_id"):
        code = (preferred.get(trip.created_by_id) or "").strip().upper()
        if len(code) == 3 and code != "USD":
            Trip.objects.filter(pk=trip.pk).update(home_currency=code)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0019_legal_versions"),
        ("trips", "0044_catalogue_links"),
    ]

    operations = [
        migrations.AddField(
            model_name="trip",
            name="home_currency",
            field=models.CharField(default="USD", help_text="The currency you think in for this trip, e.g. USD.",
                                   max_length=3),
            preserve_default=False,
        ),
        migrations.RunPython(from_creators, migrations.RunPython.noop),
    ]
