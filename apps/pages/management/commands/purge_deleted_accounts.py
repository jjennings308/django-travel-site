"""Delete accounts whose owners asked more than 30 days ago (site roadmap R13; pages.account_data).

Daily from cron on production. ``--dry-run`` lists who would go and changes nothing. Each account is
its own transaction, so one failure doesn't stop the rest (and is reported, exit 1).
"""
from django.core.management.base import BaseCommand, CommandError

from apps.pages import account_data


class Command(BaseCommand):
    help = "Delete accounts scheduled for deletion more than 30 days ago."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, dry_run=False, **options):
        due = list(account_data.due_for_purge())
        if not due:
            self.stdout.write("No accounts to delete.")
            return
        failed = 0
        for user in due:
            if dry_run:
                self.stdout.write(f"Would delete {user.username} (asked {user.deletion_requested_at:%Y-%m-%d}).")
                continue
            try:
                self.stdout.write("Deleted " + account_data.purge(user))
            except Exception as exc:  # noqa: BLE001 - report and carry on with the others
                failed += 1
                self.stderr.write(f"Could not delete {user.username}: {exc}")
        if failed:
            raise CommandError(f"{failed} account(s) could not be deleted.")
