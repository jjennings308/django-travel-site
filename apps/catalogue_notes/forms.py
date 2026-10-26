from django import forms

from apps.core.widgets import DateInput

from .models import WEEKDAYS, CatalogueNote

INPUT = {"class": "sbl-input"}


class CatalogueNoteForm(forms.ModelForm):
    """One note on a place, activity or event: what to know, and optionally which days it's closed and
    how far ahead to book."""

    closed_weekdays = forms.TypedMultipleChoiceField(
        choices=WEEKDAYS, coerce=int, required=False, widget=forms.CheckboxSelectMultiple,
        label="Closed on", help_text="Tick the days it's closed every week (it warns trips that go then).")

    class Meta:
        model = CatalogueNote
        fields = ["tone", "text", "closed_weekdays", "book_ahead", "book_ahead_unit", "booking_url", "checked_on"]
        labels = {"book_ahead": "Book ahead", "book_ahead_unit": "", "booking_url": "Booking link",
                  "checked_on": "Last checked"}
        widgets = {
            "tone": forms.Select(attrs=INPUT),
            "text": forms.Textarea(attrs={**INPUT, "rows": 3}),
            "book_ahead": forms.NumberInput(attrs={**INPUT, "min": 1, "placeholder": "3"}),
            "book_ahead_unit": forms.Select(attrs=INPUT),
            "booking_url": forms.URLInput(attrs={**INPUT, "placeholder": "https://"}),
            "checked_on": DateInput(),
        }

    def clean(self):
        data = super().clean()
        if data.get("book_ahead") and not data.get("book_ahead_unit"):
            data["book_ahead_unit"] = CatalogueNote.Unit.MONTHS
        return data
