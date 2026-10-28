"""Notes on catalogue places, cities, activities and events (docs/plans/catalogue-notes.md).

A note is written once on the thing it's about — "Cash only; no ATM near the castle", "Closed Mondays and
Tuesdays", "Timed entry: book 3 months ahead" — and shows on that catalogue page and, from N2 on, under
every trip item linked to it. Members suggest notes and staff approve them (``Approvable``); staff's notes
are published at once. What an item shows, including what it inherits, is ``services.notes_for``.
"""
from datetime import date

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from apps.activities.models import Activity
from apps.approval_system.models import Approvable
from apps.events.models import Event
from apps.locations.models import POI, City

WEEKDAYS = ((0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"), (4, "Friday"), (5, "Saturday"),
            (6, "Sunday"))


class CatalogueNote(Approvable):
    class Tone(models.TextChoices):
        TIP = "tip", "Tip"
        WARNING = "warning", "Warning"
        CRITICAL = "critical", "Critical"

    class Unit(models.TextChoices):
        DAYS = "days", "days"
        WEEKS = "weeks", "weeks"
        MONTHS = "months", "months"

    # What it's about: exactly one (catalogue_note_one_target).
    poi = models.ForeignKey(POI, on_delete=models.CASCADE, null=True, blank=True, related_name="catalogue_notes")
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, null=True, blank=True,
                                 related_name="catalogue_notes")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, null=True, blank=True, related_name="catalogue_notes")
    city = models.ForeignKey(City, on_delete=models.CASCADE, null=True, blank=True, related_name="catalogue_notes")

    tone = models.CharField(max_length=10, choices=Tone.choices, default=Tone.TIP)
    text = models.TextField(help_text="What a traveller should know, e.g. “Cash only; no ATM near the castle.”")
    closed_weekdays = ArrayField(models.PositiveSmallIntegerField(choices=WEEKDAYS), default=list, blank=True,
                                 help_text="Days it's closed every week (0 = Monday).")
    book_ahead = models.PositiveSmallIntegerField(null=True, blank=True,
                                                  help_text="How far ahead to book, e.g. 3 (with the unit).")
    book_ahead_unit = models.CharField(max_length=6, choices=Unit.choices, default=Unit.MONTHS, blank=True)
    booking_url = models.URLField(blank=True, max_length=500, help_text="Where to book, if anywhere.")
    checked_on = models.DateField(default=date.today, help_text="When this was last confirmed.")
    order = models.PositiveIntegerField(default=0)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="catalogue_notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(Approvable.Meta):
        db_table = "catalogue_notes"
        ordering = ["order", "id"]
        verbose_name = "catalogue note"
        constraints = [
            models.CheckConstraint(
                name="catalogue_note_one_target",
                condition=(Q(poi__isnull=False, activity__isnull=True, event__isnull=True, city__isnull=True)
                           | Q(poi__isnull=True, activity__isnull=False, event__isnull=True, city__isnull=True)
                           | Q(poi__isnull=True, activity__isnull=True, event__isnull=False, city__isnull=True)
                           | Q(poi__isnull=True, activity__isnull=True, event__isnull=True, city__isnull=False)),
            ),
        ]

    def __str__(self):
        return f"{self.target_name}: {self.text[:60]}"

    @property
    def target(self):
        return self.poi or self.activity or self.event or self.city

    @property
    def target_kind(self):
        return ("poi" if self.poi_id else "activity" if self.activity_id else "event" if self.event_id
                else "city")

    @property
    def target_name(self):
        target = self.target
        return target.name if target is not None else "—"

    def get_absolute_url(self):
        """The page it's about (``Approvable`` links its notifications here)."""
        from .services import target_url
        return target_url(self.target) + "#good-to-know"

    @property
    def closed_label(self):
        """"Closed Mon, Tue" (empty when it's open every day)."""
        names = dict(WEEKDAYS)
        return ("Closed " + ", ".join(names[d][:3] for d in sorted(self.closed_weekdays))) if self.closed_weekdays else ""

    @property
    def book_ahead_label(self):
        """"Book 3 months ahead" (empty without a lead time)."""
        if not self.book_ahead:
            return ""
        unit = self.book_ahead_unit or self.Unit.MONTHS
        return f"Book {self.book_ahead} {unit[:-1] if self.book_ahead == 1 else unit} ahead"
