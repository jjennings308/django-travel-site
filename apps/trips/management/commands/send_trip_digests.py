"""Email each person one list of what changed on each of their trips (site roadmap R7).

Run daily from cron (production: next to ``recount_visitors``). Takes every ``TripChange`` not yet
sent; for each trip, everyone with a grant who wants change emails (``TripGrant.notify_changes``)
and isn't inactive gets one ``trip_changed`` notification listing the changes *other people*
made — through ``notify()``, so the "Email notifications" setting and placeholder addresses are
respected. Then the changes are marked sent, so a late or repeated run never sends them twice.
Nothing changed, nothing sent. ``--dry-run`` prints what would go out and marks nothing.

It also prunes the history (site roadmap R8): changes older than ``KEEP_DAYS`` that have been
sent are deleted, so one cron line does both.
"""
from datetime import timedelta
from itertools import groupby

from django.core.management.base import BaseCommand
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.notifications.services import notify
from apps.trips.changes import recipients
from apps.trips.models import TripChange

MAX_LINES = 30
KEEP_DAYS = 180


def lines_for(changes, user):
    """The digest lines ``user`` sees: everyone's changes but their own, oldest first."""
    lines = []
    for change in changes:
        if change.actor_id == user.pk:
            continue
        who = (change.actor.get_full_name() or change.actor.username) if change.actor else "Imported"
        lines.append(f"• {who}: {change.summary}")
    return lines


class Command(BaseCommand):
    help = "Send the daily digest of changes to each trip's people."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Print what would be sent; send and mark nothing.")

    def handle(self, *args, dry_run=False, **options):
        pending = list(TripChange.objects.filter(digest_sent_at=None).select_related("trip", "actor")
                       .order_by("trip_id", "when", "id"))
        if not dry_run:
            cutoff = timezone.now() - timedelta(days=KEEP_DAYS)
            pruned, _ = TripChange.objects.filter(when__lt=cutoff).exclude(digest_sent_at=None).delete()
            if pruned:
                self.stdout.write(f"Pruned {pruned} change(s) older than {KEEP_DAYS} days.")
        if not pending:
            self.stdout.write("No changes to send.")
            return
        sent = 0
        for trip_id, group in groupby(pending, key=lambda c: c.trip_id):
            changes = list(group)
            trip = changes[0].trip
            if trip.deleted_at:
                continue
            url = reverse("trips:trip_detail", args=[trip.pk])
            for user in recipients(trip):
                lines = lines_for(changes, user)
                if not lines:
                    continue
                shown = lines[:MAX_LINES]
                if len(lines) > MAX_LINES:
                    shown.append(f"…and {len(lines) - MAX_LINES} more on the trip page.")
                count = len(lines)
                title = f"{count} change{'s' if count != 1 else ''} to “{trip.name}”"
                message = f"Since the last update, on “{trip.name}”:\n\n" + "\n".join(shown)
                if dry_run:
                    self.stdout.write(f"--- to {user.username}: {title}\n{message}\n")
                else:
                    notify(user, "trip_changed", title, message, url, obj=trip)
                sent += 1
        if dry_run:
            self.stdout.write(f"Dry run: {sent} digest(s) would be sent; nothing marked.")
            return
        with transaction.atomic():
            TripChange.objects.filter(pk__in=[c.pk for c in pending]).update(digest_sent_at=timezone.now())
        self.stdout.write(f"Sent {sent} digest(s) covering {len(pending)} change(s).")
