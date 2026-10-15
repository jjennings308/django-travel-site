"""Turn a trip's logistics tables' "A → B" rows into legs, as the trip-wide review would
with its automatic choices: arrow rows only ("possible" rows, found by the word "to", are
left), each linked to the day's existing leg when it already is one, else made a planned
leg; each converted table becomes a travel section (apps/trips/travel_tables.py).

    .venv/bin/python manage.py convert_travel_tables --trip 36            # dry run: prints the plan
    .venv/bin/python manage.py convert_travel_tables --trip 36 --apply

A second run finds nothing to do: converted tables are travel sections.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.trips import travel_tables
from apps.trips.models import Trip


class Command(BaseCommand):
    help = "Turn a trip's logistics-table travel rows into legs (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--trip", type=int, required=True, help="The trip's id.")
        parser.add_argument("--apply", action="store_true", help="Save the changes (default: print the plan).")

    def handle(self, *args, trip, apply, **options):
        trip = Trip.objects.live().filter(pk=trip).first()
        if trip is None:
            raise CommandError("No such trip.")
        plans = travel_tables.plan(trip, travel_tables.logistics_sections(trip))
        chosen = {}
        for section_plan in plans:
            day = section_plan.day
            self.stdout.write(f"Day {day.day_number} {day.date} “{section_plan.section.title or 'Logistics'}”")
            for row in section_plan.rows:
                hop = f"{row['origin']} → {row['destination']}"
                if not row["include"]:
                    self.stdout.write(f"  skip    {hop} (possible, not an arrow row)")
                    continue
                chosen[(section_plan.section.pk, row["row"])] = row
                if row["leg"] is not None:
                    self.stdout.write(f"  link    {hop} = existing leg {row['leg'].origin} → {row['leg'].destination}")
                    continue
                unmatched = [text for text, city in ((row["origin"], row["origin_city"]),
                                                     (row["destination"], row["destination_city"])) if city is None]
                extra = f" (no city for: {', '.join(unmatched)})" if unmatched else ""
                self.stdout.write(f"  create  {hop}{extra}")
            for total in section_plan.totals if any(r["include"] for r in section_plan.rows) else []:
                self.stdout.write(f"  drop    total row{': note kept — ' + total['note'] if total['note'] else ''}")
        if not chosen:
            self.stdout.write("Nothing to do.")
            return
        if not apply:
            self.stdout.write(self.style.WARNING("Dry run: nothing saved. Add --apply to convert."))
            return
        result = travel_tables.apply(trip, plans, chosen)
        self.stdout.write(self.style.SUCCESS(
            f"Made {len(result['created'])} planned legs, linked {len(result['linked'])}; "
            f"{result['sections']} tables became travel sections."))
