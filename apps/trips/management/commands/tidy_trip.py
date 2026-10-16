"""Content clean-up suggestions for a trip (docs/plans/trip-page-ux.md, U7).

    .venv/bin/python manage.py tidy_trip --trip 36            # dry run: lists every suggestion
    .venv/bin/python manage.py tidy_trip --trip 36 --apply    # applies the exact-match ones of kinds 1–2

``--apply`` only ever applies high-confidence "a line repeats an item" and "a callout repeats a task"
suggestions, with their first action. Phone numbers, trip notes, tables and "Day N" slips are left
for the review page (trips:trip_tidy). Dismissed suggestions are never applied.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.trips import tidying
from apps.trips.models import Trip

AUTO_KINDS = ("repeats_item", "callout_task")


class Command(BaseCommand):
    help = "List a trip's content clean-up suggestions (dry run unless --apply; --apply does exact matches only)."

    def add_arguments(self, parser):
        parser.add_argument("--trip", type=int, required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, trip, apply, **options):
        trip = Trip.objects.live().filter(pk=trip).first()
        if trip is None:
            raise CommandError("No such trip.")
        found = tidying.suggestions(trip)
        auto = [s for s in found if s.kind in AUTO_KINDS and s.confidence == "high" and s.actions]
        for s in found:
            mark = "auto" if s in auto else ("flag" if s.flag_only else "page")
            where = f"Day {s.day}" if s.day else "Notes"
            self.stdout.write(f"  [{mark}] {where:7} {s.kind:15} {s.before[:70]!r}")
        if not found:
            self.stdout.write("Nothing to tidy.")
            return
        if not apply:
            self.stdout.write(self.style.WARNING(f"Dry run: {len(found)} suggestions, {len(auto)} would apply with "
                                                 "--apply (the rest are for the review page)."))
            return
        applied, skipped = tidying.apply(trip, found, {s.key: s.actions[0][0] for s in auto})
        for s, why in skipped:
            self.stdout.write(self.style.WARNING(f"  skipped {s.before[:60]!r}: {why}"))
        self.stdout.write(self.style.SUCCESS(f"Applied {len(applied)} exact-match suggestions."))
