"""Move the confirmation numbers typed on legs and stays onto linked Confirmations.

Phase B of docs/plans/trip-items-and-confirmations.md. Per trip, each non-empty
``TransportLeg.confirmation_number`` / ``Lodging.confirmation_number`` is linked to the trip's
existing ``Confirmation`` with the same number (trimmed, case-insensitive) — GCH7JS typed on four
Delta legs *and* listed in Quick reference becomes that one confirmation covering the four legs.
With no match, one Confirmation per distinct number is created (provider = the leg's operator or
the stay's name). Different numbers stay separate; confirmations no item names stay loose.
``0024`` then drops the two columns. Reversible: the numbers are copied back from the links.
"""
from django.db import migrations


def _key(number):
    return " ".join((number or "").split()).casefold()


def move_numbers(apps, schema_editor=None):
    Confirmation = apps.get_model("trips", "Confirmation")
    TransportLeg = apps.get_model("trips", "TransportLeg")
    Lodging = apps.get_model("trips", "Lodging")
    by_trip = {}  # trip_id -> {key: Confirmation}

    def confirmation_for(trip_id, number, provider, label):
        known = by_trip.get(trip_id)
        if known is None:
            known = by_trip[trip_id] = {}
            for existing in Confirmation.objects.filter(trip_id=trip_id).order_by("pk"):
                known.setdefault(_key(existing.confirmation_number), existing)
        key = _key(number)
        if key not in known:
            known[key] = Confirmation.objects.create(trip_id=trip_id, confirmation_number=number.strip(),
                                                     provider=provider[:120], label=label[:200])
        return known[key]

    for leg in TransportLeg.objects.exclude(confirmation_number="").order_by("trip_id", "pk"):
        if not leg.confirmation_number.strip():
            continue
        label = f"{leg.get_mode_display() if hasattr(leg, 'get_mode_display') else 'Leg'} {leg.origin}→{leg.destination}"
        confirmation_for(leg.trip_id, leg.confirmation_number, leg.operator, label).legs.add(leg)
    for stay in Lodging.objects.exclude(confirmation_number="").order_by("trip_id", "pk"):
        if not stay.confirmation_number.strip():
            continue
        confirmation_for(stay.trip_id, stay.confirmation_number, stay.name, stay.name).stays.add(stay)


def copy_back(apps, schema_editor=None):
    Confirmation = apps.get_model("trips", "Confirmation")
    for confirmation in Confirmation.objects.all():
        for leg in confirmation.legs.all():
            if not leg.confirmation_number:
                leg.confirmation_number = confirmation.confirmation_number[:40]
                leg.save(update_fields=["confirmation_number"])
        for stay in confirmation.stays.all():
            if not stay.confirmation_number:
                stay.confirmation_number = confirmation.confirmation_number[:40]
                stay.save(update_fields=["confirmation_number"])


class Migration(migrations.Migration):

    dependencies = [
        ("trips", "0022_confirmation_links"),
    ]

    operations = [
        migrations.RunPython(move_numbers, copy_back),
    ]
