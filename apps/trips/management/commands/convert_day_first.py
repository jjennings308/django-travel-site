"""Turn a trip's to-dos with options (the old way of choosing) into "choose one" groups, as the trip's review
page would with everything ticked (day-first plan P4, retire-decision-todos D1; apps/trips/day_first.py): each
merges into a matching open choice on its day or becomes a new one, and the to-do stays open as the booking
to-do (``--tick-off`` ticks it off instead). One that looks like two choices is listed and skipped: do it on
the trip's review page. ``--all`` does every live trip, each in its own transaction under its own history line.

    .venv/bin/python manage.py convert_day_first --trip 36            # dry run: prints Merge / New per to-do
    .venv/bin/python manage.py convert_day_first --trip 36 --apply
    .venv/bin/python manage.py convert_day_first --all                # dry run, every trip, then totals
    .venv/bin/python manage.py convert_day_first --all --apply [--tick-off]

(It also converted phases, callouts, free text and choose-your-adventure sections until those were retired,
retire-old-section-types S2.) A second run finds nothing to do, apart from the skipped ones.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.trips import day_first
from apps.trips.models import Trip


class Command(BaseCommand):
    help = ("Turn to-dos with options into \"choose one\" groups, merging into a matching one, for one trip or "
            "every trip (dry run unless --apply).")

    def add_arguments(self, parser):
        which = parser.add_mutually_exclusive_group(required=True)
        which.add_argument("--trip", type=int, help="The trip's id.")
        which.add_argument("--all", dest="every", action="store_true", help="Every live trip.")
        parser.add_argument("--apply", action="store_true", help="Save the changes (default: print the plan).")
        parser.add_argument("--tick-off", action="store_true",
                            help="Tick the to-dos off (default: they stay open as booking to-dos).")

    def handle(self, *args, trip=None, every=False, apply=False, tick_off=False, **options):
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
                done = day_first.apply(one, tick_off=tick_off)
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
                skip = getattr(item, "skip", "")
                target = f"left as it is: {skip}" if skip else (after or [''])[0][:70]
                if not skip and after_kind == "New choice":
                    target = f"New choice on Day {day.day_number}: {target}"
                self.stdout.write(f"  {kind:12} {(lines or [''])[0][:60]}  →  {target}")
                count += 0 if skip else 1
        return count
