"""Turn a trip's phases, callouts and free text into notes (P3), and its choose-your-adventure sections and
decision to-dos into "choose one" groups (P4), as the trip's review page would with everything ticked
(day-first plan, apps/trips/day_first.py). ``--all`` does every live trip (retire-old-section-types S1),
each in its own transaction under its own history line.

    .venv/bin/python manage.py convert_day_first --trip 36            # dry run: prints the plan
    .venv/bin/python manage.py convert_day_first --trip 36 --apply
    .venv/bin/python manage.py convert_day_first --all                # dry run, every trip, then totals
    .venv/bin/python manage.py convert_day_first --all --apply

A second run finds nothing to do.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.trips import day_first
from apps.trips.models import Trip


class Command(BaseCommand):
    help = ("Turn phases, callouts and free text into notes, and choices into option groups, for one trip or "
            "every trip (dry run unless --apply).")

    def add_arguments(self, parser):
        which = parser.add_mutually_exclusive_group(required=True)
        which.add_argument("--trip", type=int, help="The trip's id.")
        which.add_argument("--all", dest="every", action="store_true", help="Every live trip.")
        parser.add_argument("--apply", action="store_true", help="Save the changes (default: print the plan).")

    def handle(self, *args, trip=None, every=False, apply=False, **options):
        if every:
            trips = list(Trip.objects.live().order_by("start_date", "pk"))
        else:
            trips = list(Trip.objects.live().filter(pk=trip))
            if not trips:
                raise CommandError("No such trip.")
        found = converted = with_work = 0
        for one in trips:
            groups = day_first.plan(one)
            if every:
                self.stdout.write(self.style.MIGRATE_HEADING(f"{one.name} (trip {one.pk})"))
            count = self._print(groups)
            if not count:
                self.stdout.write("  Nothing to do." if every else "Nothing to do.")
                continue
            found += count
            with_work += 1
            if apply:
                done = day_first.apply(one)
                converted += done
                self.stdout.write(self.style.SUCCESS(f"  Converted {done}." if every else f"Converted {done}."))
        if every:
            self.stdout.write(f"{len(trips)} trip{'s' if len(trips) != 1 else ''}, {with_work} with something to "
                              f"convert, {found} item{'s' if found != 1 else ''}"
                              + (f"; converted {converted}." if apply else "."))
        if found and not apply:
            self.stdout.write(self.style.WARNING("Dry run: nothing saved. Add --apply to convert."))

    def _print(self, groups):
        """Print the plan by day; return how many items it has."""
        count = 0
        for day, items in groups:
            self.stdout.write(f"Day {day.day_number} {day.date}")
            for item in items:
                kind, lines = item.before
                after_kind, after = item.after
                blocked = getattr(item, "blocked", "")
                target = f"left as it is: {blocked}" if blocked else f"{after_kind.lower()}: {(after or [''])[0][:60]}"
                self.stdout.write(f"  {kind:12} {(lines or [''])[0][:60]}  →  {target}")
                count += 0 if blocked else 1
        return count
