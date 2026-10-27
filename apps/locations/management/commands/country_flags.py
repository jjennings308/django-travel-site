"""Make each country's flag its picture (country-flags plan C1; ``apps/locations/flags.py``).

    .venv/bin/python manage.py country_flags --dry-run      # what would change
    .venv/bin/python manage.py country_flags                 # every country with a two-letter code
    .venv/bin/python manage.py country_flags --country DE

For each country whose two-letter ``iso_code`` has a committed PNG: make its flag ``Media`` (or reuse the one in
``flag_media`` while its file is there) and make it the country's picture. A photo the country had is no longer
its picture but is kept (its ``Media`` row and file stay); those countries are listed. Idempotent: a second run
reuses everything. Run after ``populate_flag_emojis`` in the seed order.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.locations import flags
from apps.locations.models import Country


class Command(BaseCommand):
    help = "Make each country's flag (from flag-icons) its picture (dry run with --dry-run)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Print what would change; save nothing.")
        parser.add_argument("--country", help="One country's two-letter code.")

    def handle(self, *args, dry_run=False, country=None, **options):
        from django.conf import settings
        if not getattr(settings, "COUNTRY_FLAGS_ENABLED", True):
            raise CommandError("COUNTRY_FLAGS_ENABLED is off in these settings.")
        countries = Country.objects.select_related("flag_media", "featured_media").order_by("name")
        if country:
            countries = countries.filter(iso_code__iexact=country.strip())
            if not countries.exists():
                raise CommandError(f"No country with the code {country!r}.")
        made, already, replaced, missing = [], [], [], []
        for row in countries:
            if not row.iso_code or len(row.iso_code.strip()) != 2 or flags.png_for(row) is None:
                missing.append(row.iso_code or f"(none: {row.name})")
                continue
            ready = row.flag_media_id is not None and flags._usable(row.flag_media)
            if ready and row.featured_media_id == row.flag_media_id:
                already.append(row)
                continue
            photo = row.featured_media_id is not None and row.featured_media_id != row.flag_media_id
            if photo:
                replaced.append((row, row.featured_media.title or f"Media {row.featured_media_id}"))
            else:
                made.append(row)
            if not dry_run:
                flags.attach(row, replace=True)
        verb = "Would make" if dry_run else "Made"
        self.stdout.write(f"{verb} {len(made)} flag picture{'s' if len(made) != 1 else ''}; "
                          f"already set: {len(already)}.")
        if replaced:
            self.stdout.write(f"{'Would replace' if dry_run else 'Replaced'} a photo with the flag for {len(replaced)} "
                              "(the photos are kept, just no longer the picture):")
            for row, title in replaced:
                self.stdout.write(f"  {row.iso_code}  {row.name}  (photo: {title})")
        if missing:
            self.stdout.write(f"No flag PNG for {len(missing)}: {', '.join(sorted(missing))}")
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run: nothing saved."))
