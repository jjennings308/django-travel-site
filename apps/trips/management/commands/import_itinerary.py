"""Import an itinerary ``.docx`` into the trips schema.

Dry-run by default. ``--apply`` is required before anything is written, and the
report is printed either way so you can read what would happen first.
"""

import json
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from trips.docx_import import parse_document
from trips.models import (
    BookingTask,
    Confirmation,
    Contact,
    Day,
    Lodging,
    Meal,
    Section,
    Traveler,
    TransportLeg,
    Trip,
)


class Command(BaseCommand):
    help = "Import an itinerary .docx into the trips schema (dry-run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("docx", help="Path to the itinerary .docx")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually write to the database. Without this, nothing is saved.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print the parsed plan as JSON instead of a prose report.",
        )
        parser.add_argument(
            "--allow-duplicate",
            action="store_true",
            help="Import even if a trip with the same name and dates already exists.",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help=(
                "Delete the existing trip with the same name and start date, then "
                "import again. Use this after fixing the parser; it discards any "
                "edits made to the existing trip in the admin."
            ),
        )
        parser.add_argument(
            "--status",
            choices=Trip.Status.values,
            default=None,
            help=(
                "Planning status for the imported trip: "
                f"{', '.join(Trip.Status.values)}. "
                "Defaults to 'starting', or to the replaced trip's status when "
                "using --replace without this flag."
            ),
        )

    def handle(self, *args, **options):
        path = options["docx"]
        # argparse validates --status on the command line, but call_command
        # merges kwargs over the parsed defaults without checking choices, and
        # Django does not validate field choices on save. Check it here so an
        # invalid status cannot be written by a programmatic caller.
        if options.get("status") not in (None, *Trip.Status.values):
            raise CommandError(
                f"--status must be one of {', '.join(Trip.Status.values)}; "
                f"got {options['status']!r}."
            )
        try:
            parsed = parse_document(path)
        except FileNotFoundError:
            raise CommandError(f"No such file: {path}")
        except Exception as exc:  # noqa: BLE001 - surface the real reason
            raise CommandError(f"Could not read {path}: {exc}")

        if not parsed.days:
            raise CommandError(
                "No 'Day N — ...' headings were found. This does not look like an "
                "itinerary document; refusing to import."
            )

        missing = self._blocking_problems(parsed)
        if missing:
            for line in missing:
                self.stderr.write(self.style.ERROR(f"  BLOCKER: {line}"))
            raise CommandError(
                f"{len(missing)} required value(s) could not be read from the "
                f"document, so this cannot be saved. Fix the source or the parser."
            )

        clash_notice = self._check_duplicate(
            parsed, options["allow_duplicate"], options["apply"], options["replace"]
        )

        if options["json"]:
            self.stdout.write(json.dumps(self._as_json(parsed), indent=2, default=str))
        else:
            self._report(parsed, options)

        if not options["apply"]:
            if clash_notice:
                self.stderr.write(
                    self.style.WARNING(f"\nNote: {clash_notice}.")
                )
            # The notices go to stderr under --json so that stdout stays pure
            # JSON and the flag can actually be piped into jq.
            notice = self.stderr if options["json"] else self.stdout
            notice.write(
                self.style.WARNING(
                    "\nDry run. Nothing was written. Re-run with --apply to save."
                )
            )
            return

        # Warnings raised *during* the write land after the report has already
        # printed, so they are tracked separately and shown afterwards rather
        # than being silently swallowed.
        write_warnings = []
        with transaction.atomic():
            replaced_pk = None
            # Resolve the status *before* anything is deleted: inheriting it
            # from the trip being replaced is only possible while that row
            # still exists.
            status, _ = self._planned_status(parsed, options)
            if options["replace"]:
                existing = Trip.objects.filter(
                    name=parsed.trip["name"], start_date=parsed.trip["start_date"]
                )
                if existing.exists():
                    replaced = existing.first()
                    # Capture the pk before deleting: Django clears the
                    # instance's pk once it is gone, so reporting it afterwards
                    # would say "Replaced Trip None".
                    replaced_pk = replaced.pk
                    # Cascades clear the days, sections, meals, lodging, transport,
                    # confirmations and contacts that hang off the trip.
                    replaced.delete()
            trip = self._write(parsed, status=status, warn=write_warnings.append)
        if replaced_pk is not None:
            self.stdout.write(
                self.style.WARNING(f"Replaced Trip {replaced_pk} with this import.")
            )
        if write_warnings:
            self.stdout.write(
                self.style.WARNING(
                    f"\n=== {len(write_warnings)} warning(s) raised while saving ==="
                )
            )
            for line in write_warnings:
                self.stdout.write(self.style.WARNING(f"  - {line}"))
        self.stdout.write(self.style.SUCCESS(f"\nSaved Trip {trip.pk} — {trip.name}"))

    # ------------------------------------------------------------------
    # validation
    # ------------------------------------------------------------------

    def _blocking_problems(self, parsed):
        problems = []
        if not parsed.trip.get("name"):
            problems.append("the trip has no name")
        if not parsed.trip.get("start_date") or not parsed.trip.get("end_date"):
            problems.append("the trip has no start_date/end_date")
        for leg in parsed.transport:
            missing = [
                key
                for key in ("departure_local", "origin", "destination")
                if not leg.get(key)
            ]
            if missing:
                problems.append(
                    f"leg {leg['service_number'] or '?'} is missing "
                    f"{', '.join(missing)}"
                )
        for record in parsed.lodging:
            if not record.get("check_in") or not record.get("check_out"):
                problems.append(f"lodging {record.get('name', '?')!r} has no stay dates")
        for record in parsed.days:
            if not record["date"]:
                problems.append(f"day {record['day_number']} has no date")
        return problems

    def _planned_status(self, parsed, options):
        """Resolve the status an ``--apply`` would save, and say where it came from.

        Read-only and safe to call during a dry run, so the report can show the
        value that would actually be written rather than a guess. Precedence is
        an explicit ``--status``, then the status of a trip being replaced, then
        the field default. Inheriting on ``--replace`` matters because a re-import
        is usually a parser fix, and silently resetting a finished trip back to
        "starting" would be a surprising side effect of fixing a typo.
        """
        if options.get("status"):
            return options["status"], "from --status"
        if options.get("replace"):
            existing = Trip.objects.filter(
                name=parsed.trip["name"], start_date=parsed.trip["start_date"]
            ).first()
            if existing:
                return existing.status, f"inherited from Trip {existing.pk}"
        return Trip.Status.STARTING, "default"

    def _check_duplicate(self, parsed, allow, applying, replace):
        """Guard against importing the same document twice.

        A dry run is only a preview, so it reports the clash and carries on --
        being able to re-preview a document that is already in the database is
        the whole point of the dry run. Only a real write is blocked.
        """
        if allow or replace:
            return None
        existing = Trip.objects.filter(
            name=parsed.trip["name"], start_date=parsed.trip["start_date"]
        )
        if not existing.exists():
            return None
        clash = existing.first()
        message = (
            f"A trip named {parsed.trip['name']!r} starting "
            f"{parsed.trip['start_date']} already exists (pk {clash.pk})"
        )
        if not applying:
            return f"{message}; this is only a preview, so it is not a problem yet"
        raise CommandError(
            f"{message}. Pass --replace to delete it and import again, "
            f"--allow-duplicate to import a second copy, or delete it in the "
            f"admin yourself."
        )

    # ------------------------------------------------------------------
    # reporting
    # ------------------------------------------------------------------

    def _as_json(self, parsed):
        data = {k: v for k, v in vars(parsed).items()}
        data["counts"] = parsed.counts()
        for leg in parsed.transport:
            leg.pop("_local", None)
        return data

    def _report(self, parsed, options):
        trip = parsed.trip
        out = self.stdout.write
        status, origin = self._planned_status(parsed, options)

        out(self.style.MIGRATE_HEADING("\n=== Trip ==="))
        out(f"  name         {trip['name']}")
        out(f"  destination  {trip.get('destination', '')}")
        out(f"  dates        {trip.get('start_date')} to {trip.get('end_date')}")
        out(f"  status       {status}  ({origin})")
        if trip.get("notes"):
            out(f"  notes        {len(trip['notes'])} chars from the overview")

        if parsed.travelers:
            out(self.style.MIGRATE_HEADING("\n=== Travelers ==="))
            for traveler in parsed.travelers:
                out(f"  - {traveler['name']}")

        if parsed.transport:
            out(self.style.MIGRATE_HEADING("\n=== Transport (local time, as written) ==="))
            for leg in parsed.transport:
                out(
                    f"  {leg['operator']} {leg['service_number']:>5}  "
                    f"{leg['origin']}->{leg['destination']}  "
                    f"dep {leg['departure_local'] or '??'}  "
                    f"arr {leg['arrival_local'] or '??'}"
                    f" on {leg['arrival_date'] or '?'}  "
                    f"[{leg['origin_timezone'] or 'UTC?'} -> "
                    f"{leg['destination_timezone'] or 'UTC?'}]"
                )
                if leg.get("notes"):
                    out(f"      {leg['notes']}")

        if parsed.lodging:
            out(self.style.MIGRATE_HEADING("\n=== Lodging ==="))
            for record in parsed.lodging:
                out(
                    f"  {record['name']}  {record['check_in']} -> {record['check_out']}"
                    f"  nightly {record['nightly_rate'] or '-'} {record['currency']}"
                )
                if record.get("address"):
                    out(f"      {record['address']}")

        out(self.style.MIGRATE_HEADING("\n=== Days ==="))
        for record in parsed.days:
            out(
                f"  Day {record['day_number']}  {record['date']}  "
                f"meals_included={record['meals_included']}  "
                f"{len(record['sections'])} sections, {len(record['meals'])} meals"
            )
            out(f"      theme: {record['theme']}")
            roster = record.get("roster")
            if roster:
                out(f"      roster: {', '.join(roster)}")
            for meal in record["meals"]:
                out(
                    f"      meal: {meal['meal_type']:8} {meal['name']}  "
                    f"{meal['price_range'] or '-'}  {meal['cuisine'] or '-'}"
                )
            for section in record["sections"]:
                out(
                    f"      {section['order']:>2}. {section['section_type']:22} "
                    f"{section['icon']}{section['title'][:52]}"
                )

        if parsed.confirmations:
            out(self.style.MIGRATE_HEADING("\n=== Confirmations ==="))
            for record in parsed.confirmations:
                out(f"  {record['label'][:38]:40} {record['confirmation_number']}")

        if parsed.booking_tasks:
            out(self.style.MIGRATE_HEADING("\n=== Booking tasks ==="))
            for record in parsed.booking_tasks:
                out(
                    f"  {record['order']:>2}. [{record['priority']}] "
                    f"{record['title'][:62]}"
                )

        if parsed.contacts:
            out(self.style.MIGRATE_HEADING("\n=== Contacts ==="))
            for record in parsed.contacts:
                out(f"  {record['name'][:44]:46} {record['phone']}")

        counts = parsed.counts()
        out(self.style.MIGRATE_HEADING("\n=== Totals ==="))
        out("  " + ", ".join(f"{k}={v}" for k, v in counts.items()))

        if parsed.warnings:
            out(self.style.MIGRATE_HEADING(f"\n=== {len(parsed.warnings)} warning(s) ==="))
            for message in parsed.warnings:
                out(self.style.WARNING(f"  ! {message}"))

    # ------------------------------------------------------------------
    # writing
    # ------------------------------------------------------------------

    def _write(self, parsed, status=None, warn=None):
        trip = Trip.objects.create(
            name=parsed.trip["name"],
            destination=parsed.trip.get("destination", ""),
            start_date=parsed.trip["start_date"],
            end_date=parsed.trip["end_date"],
            notes=parsed.trip.get("notes", ""),
            status=status or Trip.Status.STARTING,
        )
        # get_or_create, not create: a re-import must reuse the roster rows
        # that already exist, or every --replace would add a second "James
        # Jennings" beside the first and split one person across two rows.
        travelers = [
            Traveler.objects.get_or_create(
                name=record["name"],
                defaults={k: v for k, v in record.items() if k != "name"},
            )[0]
            for record in parsed.travelers
        ]
        if travelers:
            trip.travelers.set(travelers)

        for record in parsed.transport:
            TransportLeg.objects.create(
                trip=trip,
                mode=record["mode"],
                operator=record["operator"],
                service_number=record["service_number"],
                confirmation_number=record["confirmation_number"],
                origin=record["origin"],
                destination=record["destination"],
                origin_timezone=record["origin_timezone"],
                destination_timezone=record["destination_timezone"],
                departure_at=self._local_to_utc(record["departure_local"], record["origin_timezone"], record),
                arrival_at=self._local_to_utc(
                    record["arrival_local"],
                    record["destination_timezone"],
                    record,
                    arrival=True,
                ),
                currency=record["currency"],
                notes=record["notes"],
            )

        for record in parsed.lodging:
            Lodging.objects.create(
                trip=trip,
                name=record["name"],
                address=record["address"],
                confirmation_number=record["confirmation_number"],
                check_in=record["check_in"],
                check_out=record["check_out"],
                nightly_rate=record["nightly_rate"] or None,
                currency=record["currency"],
                notes=record["notes"],
            )

        for record in parsed.confirmations:
            Confirmation.objects.create(trip=trip, **record)

        for record in parsed.contacts:
            Contact.objects.create(trip=trip, **record)

        for record in parsed.days:
            day = Day.objects.create(
                trip=trip,
                day_number=record["day_number"],
                date=record["date"],
                theme=record["theme"],
                meals_included=record["meals_included"],
            )
            if warn:
                self._set_roster(day, record.get("roster"), travelers, warn)
            for section in record["sections"]:
                Section.objects.create(day=day, **section)
            for meal in record["meals"]:
                Meal.objects.create(day=day, **meal)

        for record in parsed.booking_tasks:
            BookingTask.objects.create(trip=trip, **record)

        return trip

    def _set_roster(self, day, roster, travelers, warn):
        """Attach the day's roster, or leave it blank to mean "whole trip".

        A badge that resolves to *everybody* is left blank rather than stored.
        Writing all six names would be redundant — blank already means the whole
        group — and it would make ``Day.is_split`` report True on days where
        nobody split up, which is the one thing that field exists to say.
        """
        if not roster:
            return
        by_name = {traveler.name: traveler for traveler in travelers}
        chosen = []
        for name in roster:
            traveler = by_name.get(name)
            if traveler is None:
                warn(
                    f"Roster name {name!r} on day {day.day_number} matches no "
                    "traveler, so it is not attached"
                )
                continue
            chosen.append(traveler)
        if len(chosen) == len(travelers):
            # The whole group: blank says this, and saying it with a row says
            # it less clearly.
            return
        if chosen:
            day.travelers.set(chosen)

    def _local_to_utc(self, local_time, timezone_name, record, arrival=False):
        """Convert an 'HH:MM:SS' local time to an aware UTC datetime.

        A blank timezone falls back to UTC, which makes the stored value wrong
        by the offset but never ambiguous -- the same degradation the admin form
        and the model helpers use. The dry run warns about every blank one.
        """
        from datetime import datetime, timezone as dt_timezone

        date = record["arrival_date"] if arrival else record["departure_date"]
        naive = datetime.fromisoformat(f"{date}T{local_time}")
        zone = ZoneInfo(timezone_name) if timezone_name else ZoneInfo("UTC")
        return naive.replace(tzinfo=zone).astimezone(tz=dt_timezone.utc)
