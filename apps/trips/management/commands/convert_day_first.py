"""Turn a trip's phases, callouts and free text into notes, as the trip's review page would with every
section ticked (day-first plan P3, apps/trips/day_first.py).

    .venv/bin/python manage.py convert_day_first --trip 36            # dry run: prints the plan
    .venv/bin/python manage.py convert_day_first --trip 36 --apply

A second run finds nothing to do.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.trips import day_first
from apps.trips.models import Trip


class Command(BaseCommand):
    help = "Turn a trip's phases, callouts and free text into notes (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--trip", type=int, required=True, help="The trip's id.")
        parser.add_argument("--apply", action="store_true", help="Save the changes (default: print the plan).")

    def handle(self, *args, trip, apply, **options):
        trip = Trip.objects.live().filter(pk=trip).first()
        if trip is None:
            raise CommandError("No such trip.")
        groups = day_first.plan(trip)
        for day, items in groups:
            self.stdout.write(f"Day {day.day_number} {day.date}")
            for item in items:
                kind, lines = item.before
                _, after = item.after
                self.stdout.write(f"  {kind:12} {(lines or [''])[0][:60]}  →  note: {(after or [''])[0][:60]}")
        if not groups:
            self.stdout.write("Nothing to do.")
            return
        if not apply:
            self.stdout.write(self.style.WARNING("Dry run: nothing saved. Add --apply to convert."))
            return
        count = day_first.apply(trip)
        self.stdout.write(self.style.SUCCESS(f"Turned {count} sections into notes."))
