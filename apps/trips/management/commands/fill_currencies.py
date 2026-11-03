"""Store the currency of costs that have none (docs/plans/blank-currencies.md, CU1).

    .venv/bin/python manage.py fill_currencies                     # dry run: every trip
    .venv/bin/python manage.py fill_currencies --trip 36 --apply   # saves, one history line per trip

Lists every leg, stay, activity, meal, choice option and confirmation with an amount and a blank currency, and
the code it would set — the item's place's, as the site already reads it (``currencies.currency_of``):
"Neuschwanstein Castle (Day 15): EUR, from Schwangau". Items with no amount stay blank.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.trips import currencies
from apps.trips.models import Trip


class Command(BaseCommand):
    help = "Fill in the currency of costs that have none, from their place (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--trip", type=int)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, trip=None, apply=False, **options):
        trips = Trip.objects.live().order_by("pk")
        if trip is not None:
            trips = trips.filter(pk=trip)
            if not trips.exists():
                raise CommandError("No such trip.")
        total = 0
        for one in trips:
            rows = currencies.blanks(one)
            if not rows:
                continue
            self.stdout.write(f"{one.name} (#{one.pk})")
            for row in rows:
                where = f" (Day {row['day'].day_number})" if row["day"] is not None else ""
                self.stdout.write(f"  {row['label']}{where}: {row['code']}, {row['why']}")
            if apply:
                currencies.fill(one, rows)
            total += len(rows)
        if not total:
            self.stdout.write("No costs without a currency.")
        elif apply:
            self.stdout.write(self.style.SUCCESS(f"Filled in {total} missing currenc{'y' if total == 1 else 'ies'}."))
        else:
            self.stdout.write(self.style.WARNING(f"Dry run: {total} to fill in; run with --apply to save."))
