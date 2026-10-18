"""Fetch the ECB's reference exchange rates into ``ExchangeRate`` (site roadmap R10).

Daily from cron after the ECB publishes (around 16:00 CET), e.g. 17:30 Europe time. The first run
should be ``--history all`` (every day since 1999) or ``--history 90d``. A failure to reach the ECB
or a file that isn't rates is an error (exit 1) and writes nothing.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.core import rates


class Command(BaseCommand):
    help = "Fetch the European Central Bank's reference exchange rates."

    def add_arguments(self, parser):
        parser.add_argument("--history", choices=["90d", "all"],
                            help="Also fetch the last 90 days, or every day since 1999 (first run).")

    def handle(self, *args, history=None, **options):
        try:
            days = rates.parse(rates.fetch(history or "daily"))
        except rates.RatesError as exc:
            raise CommandError(str(exc)) from exc
        written = rates.store(days)
        newest = max(days)
        self.stdout.write(f"Stored {written} rates for {len(days)} day(s); newest {newest}.")
