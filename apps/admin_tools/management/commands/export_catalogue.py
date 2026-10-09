"""Write the published catalogue to CSV files in the import format, one per kind.

    python manage.py export_catalogue [directory]   # default: ./catalogue-export-<date>/

Files can be edited and loaded back on /staff/import/, in this order: countries,
regions, cities, places, activities, events.
"""
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.admin_tools.importers import IMPORT_ORDER, KINDS, export_csv


class Command(BaseCommand):
    help = "Export countries, regions, cities, places, activities and events to CSV (import format)."

    def add_arguments(self, parser):
        parser.add_argument("directory", nargs="?", help="Folder to write into (created if missing).")

    def handle(self, *args, directory=None, **options):
        folder = Path(directory or f"catalogue-export-{timezone.localdate():%Y-%m-%d}")
        folder.mkdir(parents=True, exist_ok=True)
        for number, kind in enumerate(IMPORT_ORDER, start=1):
            path = folder / f"{number}-{kind}.csv"
            with path.open("w", newline="", encoding="utf-8-sig") as out:
                count = export_csv(kind, out)
            self.stdout.write(f"{path}: {count} {KINDS[kind].label.lower()}")
