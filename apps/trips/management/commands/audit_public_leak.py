"""Report anything in a trip's public shape that should not be public.

    .venv/bin/python manage.py audit_public_leak
    .venv/bin/python manage.py audit_public_leak --json
    .venv/bin/python manage.py audit_public_leak --trip 31

Reads only, writes nothing, and exits non-zero when it finds something — so it
works as a check rather than something you have to read carefully.

**Why this is a command and not just a test.** The leaks worth catching are all
in real data: a day theme reading "Fly to England | Sara & Henry fly home", a
hotel note carrying "Guest Name: James Jennings". A synthetic fixture would not
contain those, so a test built on fixtures would pass while the actual trips
leaked. `manage.py test` builds its own empty database and so cannot see the
imported rows at all; this command runs against whatever database is configured,
which means it *can* see them.

That makes it read-only by necessity rather than by preference: pointing it at
the development database is safe precisely because it only reads.

It is a heuristic, and the important caveat is that it can only tell you when the
allowlist in `trips/public.py` has been weakened. It cannot prove a shape
is safe — that is the allowlist's job, and `trips/tests/test_public.py`
checks the allowlist. This catches the day after someone adds a field back.
"""

import json

from django.core.management.base import BaseCommand

from trips.models import Trip
from trips.public import find_leaks, public_trip, trip_leak_finders


class Command(BaseCommand):
    help = "Report traveller names, confirmation numbers and flight routes in the public view of each trip."

    def add_arguments(self, parser):
        parser.add_argument(
            "--trip",
            type=int,
            action="append",
            dest="trip_ids",
            help="Only check these trip ids. Repeatable. Defaults to every live trip.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print findings as JSON and nothing else, so it can be piped into jq.",
        )

    def handle(self, *args, **options):
        trips = Trip.objects.live().prefetch_related(
            "days__meals", "days__sections", "travelers", "confirmations",
            "lodging", "transport",
        )
        if options["trip_ids"]:
            trips = trips.filter(pk__in=options["trip_ids"])

        report = []
        for trip in trips:
            names, numbers = trip_leak_finders(trip)
            shape = public_trip(trip)
            findings = [
                {"severity": severity, "detail": detail}
                for severity, detail in find_leaks(shape, names=names, numbers=numbers)
            ]
            report.append(
                {
                    "trip": trip.pk,
                    "title": trip.public_title,
                    "days": trip.days.count(),
                    "has_public_token": trip.public_token is not None,
                    "findings": findings,
                }
            )

        if options["json"]:
            print(json.dumps(report, indent=2, default=str))
        else:
            self.print_report(report)

        # Only `certain` findings fail the check. A name word is often also a
        # place name — this data has a "St. James Hotel" on a trip with a
        # traveller called James — and a check that can never pass is a check
        # nobody runs. Possible findings are printed for review, not enforced.
        certain = sum(
            1 for row in report for f in row["findings"] if f["severity"] == "certain"
        )
        raise SystemExit(1 if certain else 0)

    def print_report(self, report):
        if not report:
            self.stdout.write("No live trips to check.")
            return
        for row in report:
            state = "public" if row["has_public_token"] else "not shared"
            header = f"trip {row['trip']}: {row['title']} ({row['days']} days, {state})"
            certain = [f for f in row["findings"] if f["severity"] == "certain"]
            possible = [f for f in row["findings"] if f["severity"] == "possible"]

            if certain:
                self.stdout.write(self.style.ERROR(header))
            else:
                self.stdout.write(self.style.SUCCESS(header))

            for finding in certain:
                self.stdout.write(f"    LEAK      {finding['detail']}")
            for finding in possible:
                # Worth a look, not necessarily wrong: "St. James Hotel" is a
                # restaurant on a trip with a traveller called James.
                self.stdout.write(
                    f"    review    {finding['detail']} "
                    f"(a name word may also be a place)"
                )
            if not certain and not possible:
                self.stdout.write("    clean")