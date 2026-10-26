from django.apps import AppConfig


class CatalogueNotesConfig(AppConfig):
    """Notes on catalogue places, activities and events that flow into trips (docs/plans/catalogue-notes.md)."""

    name = "apps.catalogue_notes"
    label = "catalogue_notes"
    verbose_name = "Catalogue notes"
