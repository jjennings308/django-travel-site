"""Look up coordinates for stays (Lodging) that have an address but no pin yet; with
--fill-days, also give each stay's nights (days with no city) the stay's city.

One request a second, as OpenStreetMap's Nominatim usage policy asks. Run once after
deploying the stay locations, and any time later to fill in stays added through
imports (forms look addresses up as they're saved)."""
import time

from django.core.management.base import BaseCommand

from apps.trips.models import Lodging


class Command(BaseCommand):
    help = "Fill in map coordinates for stays from their addresses (one lookup a second)."

    def add_arguments(self, parser):
        parser.add_argument("--trip", type=int, help="Only this trip's stays")
        parser.add_argument("--retry", action="store_true", help="Also retry addresses that weren't found before")
        parser.add_argument("--fill-days", action="store_true",
                            help="Also set the city on days a stay covers that have none (no lookups needed)")

    def handle(self, *args, trip=None, retry=False, fill_days=False, **options):
        stays = Lodging.objects.filter(latitude__isnull=True).exclude(address="")
        if trip:
            stays = stays.filter(trip_id=trip)
        found = missed = 0
        for n, stay in enumerate(stays.order_by("pk")):
            if retry:
                stay.geocoded_address = ""
            if stay.address.strip() == stay.geocoded_address:
                continue  # looked up before and not found; --retry to try again
            if n:
                time.sleep(1)
            stay.locate()
            stay.save(update_fields=["latitude", "longitude", "geocoded_address"])
            if stay.latitude is not None:
                found += 1
                self.stdout.write(f"  {stay.name}: {stay.latitude}, {stay.longitude}")
            else:
                missed += 1
                self.stdout.write(f"  {stay.name}: not found ({stay.address!r})")
        self.stdout.write(self.style.SUCCESS(f"{found} placed, {missed} not found."))
        if fill_days:
            stays = Lodging.objects.filter(city__isnull=False).select_related("trip", "city")
            if trip:
                stays = stays.filter(trip_id=trip)
            days = 0
            for stay in stays.order_by("check_in"):
                n = stay.fill_day_cities()
                if n:
                    days += n
                    self.stdout.write(f"  {stay.name}: {n} day{'s' if n != 1 else ''} set to {stay.city.name}")
            self.stdout.write(self.style.SUCCESS(f"{days} day city(ies) filled from stays."))
