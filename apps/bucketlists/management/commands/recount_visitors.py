"""Recompute visitor_count on places, cities, regions and countries.

Run nightly (trips count once their end date has passed, which no save marks):
    python manage.py recount_visitors
"""
from django.core.management.base import BaseCommand

from apps.bucketlists.visitors import recount


class Command(BaseCommand):
    help = "Recount members who have been to each place, city, region and country."

    def handle(self, *args, **options):
        self.stdout.write(f"{recount()} count(s) changed.")
