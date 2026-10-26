"""Recompute visitor_count on places, cities, regions and countries, and trip_count on places,
activities and events (site roadmap R18).

Run nightly (trips count once their end date has passed, which no save marks):
    python manage.py recount_visitors
"""
from django.core.management.base import BaseCommand

from apps.bucketlists.visitors import recount
from apps.trips import catalogue_counts


class Command(BaseCommand):
    help = "Recount members who have been to each place, city, region and country, and trips per place and activity."

    def handle(self, *args, **options):
        self.stdout.write(f"{recount()} visitor count(s) changed.")
        self.stdout.write(f"{catalogue_counts.recount()} trip count(s) changed.")
