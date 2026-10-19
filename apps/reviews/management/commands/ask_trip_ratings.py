"""Ask everyone on recently finished trips to rate their places (site roadmap R17).

The daily ``send_trip_digests`` already does this (through ``trips.signals.daily_run``); this command
is for running it by hand. Each person is asked once per trip, ever.
"""
from django.core.management.base import BaseCommand

from apps.reviews import trip_ratings


class Command(BaseCommand):
    help = "Send 'How was your trip?' prompts for trips that have just finished."

    def handle(self, *args, **options):
        self.stdout.write(f"Sent {trip_ratings.ask()} rating prompt(s).")
