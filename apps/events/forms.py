# events/forms.py
from django import forms

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import City, Country

from apps.activities.models import Activity, ActivityCategory

from .models import Event

INPUT = {"class": "sbl-input"}


class EventForm(forms.ModelForm):
    """What a user fills in to submit (or edit) an event. Approval, counters and
    the admin-only fields are left out; staff manage those in the admin."""

    class Meta:
        model = Event
        fields = [
            "related_activity", "name", "category", "short_description", "description",
            "city", "country", "location_text", "venue_name", "venue_address",
            "start_date", "end_date", "is_all_day", "start_time", "end_time",
            "event_type", "organizer", "indoor_outdoor", "age_restriction",
            "is_free", "ticket_price_min", "ticket_price_max", "currency", "ticket_url",
            "website", "what_to_bring",
        ]
        widgets = {
            "name": forms.TextInput(attrs={**INPUT, "placeholder": "e.g. Riverfront Jazz Festival"}),
            "short_description": forms.TextInput(attrs={**INPUT, "placeholder": "One line for event cards"}),
            "description": forms.Textarea(attrs={**INPUT, "rows": 5}),
            "location_text": forms.TextInput(attrs={**INPUT, "placeholder": "e.g. Hallstatt"}),
            "venue_name": forms.TextInput(attrs=INPUT),
            "venue_address": forms.TextInput(attrs=INPUT),
            "start_date": forms.DateInput(attrs={**INPUT, "type": "date"}, format="%Y-%m-%d"),
            "end_date": forms.DateInput(attrs={**INPUT, "type": "date"}, format="%Y-%m-%d"),
            "start_time": forms.TimeInput(attrs={**INPUT, "type": "time"}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={**INPUT, "type": "time"}, format="%H:%M"),
            "organizer": forms.TextInput(attrs=INPUT),
            "ticket_price_min": forms.NumberInput(attrs={**INPUT, "step": "0.01", "min": "0"}),
            "ticket_price_max": forms.NumberInput(attrs={**INPUT, "step": "0.01", "min": "0"}),
            "currency": forms.TextInput(attrs={**INPUT, "maxlength": 3, "placeholder": "USD"}),
            "ticket_url": forms.URLInput(attrs={**INPUT, "placeholder": "https://"}),
            "website": forms.URLInput(attrs={**INPUT, "placeholder": "https://"}),
            "what_to_bring": forms.Textarea(attrs={**INPUT, "rows": 2}),
            "is_all_day": forms.CheckboxInput(attrs={"class": "sbl-check"}),
            "is_free": forms.CheckboxInput(attrs={"class": "sbl-check"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["city"].queryset = (
            City.objects.filter(approval_status=ApprovalStatus.APPROVED)
            .select_related("country").order_by("country__name", "name")
        )
        self.fields["city"].label_from_instance = lambda c: f"{c.name}, {c.country.name}"
        self.fields["city"].required = False
        self.fields["city"].empty_label = "Choose a city…"
        self.fields["country"].queryset = Country.objects.filter(
            approval_status=ApprovalStatus.APPROVED).order_by("name")
        self.fields["country"].empty_label = "Choose a country…"
        self.fields["location_text"].label = "City / town"
        self.fields["category"].queryset = ActivityCategory.objects.filter(is_active=True)
        self.fields["category"].required = False  # falls back to the activity's category
        self.fields["related_activity"].queryset = Activity.get_public_activities().order_by("name")
        self.fields["related_activity"].label = "This is a date for (activity)"
        self.fields["related_activity"].empty_label = "Not tied to an activity"
        self.fields["related_activity"].help_text = "e.g. Oktoberfest 2027 is a date for the Oktoberfest activity."
        # These have model defaults but aren't blank=True; don't make users fill them in.
        for name in ("event_type", "age_restriction", "currency"):
            self.fields[name].required = False
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.Select) and not isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "sbl-input")

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("category"):
            activity = cleaned.get("related_activity")
            if activity:
                cleaned["category"] = activity.category
            else:
                self.add_error("category", "Choose a category (or the activity this is a date for).")
        # Either a catalogue city, or (city not listed) a country plus the town name.
        if cleaned.get("city"):
            cleaned["country"], cleaned["location_text"] = None, ""
        else:
            text = (cleaned.get("location_text") or "").strip()
            cleaned["location_text"] = text
            if not cleaned.get("country") or not text:
                self.add_error("city", "Choose a city, or tick “City not listed” and enter the country and town.")
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "The end date can't be before the start date.")
        if not cleaned.get("is_all_day") and cleaned.get("start_time") and cleaned.get("end_time") \
                and (not end or end == start) and cleaned["end_time"] < cleaned["start_time"]:
            self.add_error("end_time", "The end time can't be before the start time on a one-day event.")
        lo, hi = cleaned.get("ticket_price_min"), cleaned.get("ticket_price_max")
        if lo is not None and hi is not None and hi < lo:
            self.add_error("ticket_price_max", "The maximum price can't be below the minimum.")
        for name in ("event_type", "age_restriction", "currency"):
            if not cleaned.get(name):
                cleaned[name] = Event._meta.get_field(name).get_default()
        cleaned["currency"] = cleaned["currency"].upper()
        return cleaned
