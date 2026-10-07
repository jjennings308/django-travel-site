"""Merge traveler rows that are the same person under two names.

The roster grew one row per *spelling* rather than per person: the Taos
import used full names ("Debbie Fowler"), the Europe draft used first names
("Debbie"), and the same six people ended up represented twice — with the
Europe trip's membership sitting on the rows that have no account. This pairs
each first-name row into the full-name row it belongs to, moves the trips and
day rosters across, carries over any detail the full-name row is missing, and
deletes the donor.

Pairing rule: a row is a donor when exactly one *other* traveler's name
begins with its whole name as the first word ("Debbie" matches "Debbie
Fowler"). Anything less than a one-to-one match is reported and left alone —
merging the wrong way would silently attach one person's trips to another.
Dry-run is the default; ``--apply`` writes inside one transaction, so a pair
that fails part-way leaves the roster exactly as it was.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.trips.models import Traveler

DETAIL_FIELDS = (
    "home_airport",
    "dietary_notes",
    "mobility_notes",
    "passport_country",
    "seat_preference",
    "cabin_preference",
    "bed_preference",
    "meal_preference",
    "known_traveler_number",
    "redress_number",
    "passport_number",
    "passport_expires",
)


class Command(BaseCommand):
    help = "Merge same-person traveler rows (dry-run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually write to the database. Without this, nothing is saved.",
        )

    def handle(self, *args, **options):
        pairs, skipped = self._plan()

        for donor, keeper, info in pairs:
            self.stdout.write(f'  "{donor.name}" -> "{keeper.name}"')
            if info["trips"]:
                self.stdout.write(f"      trips: {', '.join(info['trips'])}")
            if info["days"]:
                self.stdout.write(f"      days: {info['days']}")
            if info["fills"]:
                self.stdout.write(f"      fills: {', '.join(info['fills'])}")
            if info["conflicts"]:
                self.stdout.write(
                    f"      kept {keeper.name}'s: {', '.join(info['conflicts'])}"
                )
            if info["account"]:
                self.stdout.write(f"      account: {info['account']}")
            if info["memberships"]:
                self.stdout.write(f"      programs: {', '.join(info['memberships'])}")
            if info["membership_conflicts"]:
                self.stdout.write(
                    f"      kept {keeper.name}'s programs: "
                    f"{', '.join(info['membership_conflicts'])}"
                )

        for donor_name, reason in skipped:
            self.stdout.write(self.style.WARNING(f"  skipped {donor_name!r}: {reason}"))

        if not pairs:
            self.stdout.write("Nothing to merge.")
        elif options["apply"]:
            with transaction.atomic():
                self._merge(pairs)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Merged {len(pairs)} traveler(s); "
                    f"{len(pairs)} row(s) deleted."
                )
            )
        else:
            self.stdout.write(
                f"\nWould merge {len(pairs)} traveler(s). Nothing was written."
            )
            self.stderr.write(
                self.style.WARNING("This was a dry run. Re-run with --apply to save.")
            )

    def _plan(self):
        """Pair up the rows and describe every change, writes or no writes.

        Built once so the dry run and the write describe exactly the same set
        of edits rather than the write re-deciding.
        """
        travelers = list(Traveler.objects.select_related("user").order_by("pk"))
        pairs, skipped = [], []
        claimed = set()

        for donor in travelers:
            if donor.pk in claimed:
                continue
            matches = [
                t
                for t in travelers
                if t.pk != donor.pk and t.name.split()[:1] == [donor.name]
            ]
            if not matches:
                continue
            if len(matches) > 1:
                skipped.append(
                    (donor.name, "matches " + " and ".join(repr(m.name) for m in matches))
                )
                continue
            keeper = matches[0]
            if keeper.pk in claimed:
                skipped.append((donor.name, f'"{keeper.name}" is already a keeper'))
                continue
            if donor.user_id and keeper.user_id:
                skipped.append(
                    (donor.name, f'both rows have an account ({donor.user.username})')
                )
                continue
            claimed.add(keeper.pk)
            pairs.append((donor, keeper, self._describe(donor, keeper)))

        return pairs, skipped

    def _describe(self, donor, keeper):
        trips = [str(t) for t in donor.trips.all()]
        fills, conflicts = [], []
        for field in DETAIL_FIELDS:
            ours, theirs = getattr(donor, field), getattr(keeper, field)
            if ours and not theirs:
                fills.append(field)
            elif ours and theirs and ours != theirs:
                conflicts.append(field)
        account = None
        if donor.user_id:
            account = donor.user.username
        # One row per program per person, so a program both rows have is a
        # conflict, and the keeper's row wins as for every other field.
        keeper_programs = set(keeper.memberships.values_list("program", flat=True))
        memberships, membership_conflicts = [], []
        for program in donor.memberships.values_list("program", flat=True):
            (membership_conflicts if program in keeper_programs else memberships).append(
                program
            )
        return {
            "memberships": memberships,
            "membership_conflicts": membership_conflicts,
            "trips": trips,
            "days": donor.days.count(),
            "fills": fills,
            "conflicts": conflicts,
            "account": account,
        }

    def _merge(self, pairs):
        for donor, keeper, info in pairs:
            for trip in donor.trips.all():
                trip.travelers.add(keeper)
            for day in donor.days.all():
                day.travelers.add(keeper)
            # Queryset updates on purpose: both a save() here and a save() on
            # the keeper would fire the account-linking signal mid-merge.
            if info["account"]:
                Traveler.objects.filter(pk=donor.pk).update(user=None)
                Traveler.objects.filter(pk=keeper.pk, user=None).update(
                    user_id=donor.user_id
                )
            if info["fills"]:
                for field in info["fills"]:
                    setattr(keeper, field, getattr(donor, field))
                keeper.save(update_fields=info["fills"])
            # Before the delete: memberships CASCADE with the donor.
            donor.memberships.filter(program__in=info["memberships"]).update(
                traveler=keeper
            )
            # Deleting the donor drops its trip/day memberships on its own;
            # the keeper was added to them above, so nothing else is lost.
            donor.delete()
