# bucketlists/forms.py
from django import forms

from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event
from apps.locations.models import POI

from .models import BucketListCategory, BucketListItem

INPUT = {"class": "sbl-input"}


class BucketListItemForm(forms.ModelForm):
    """Add/edit an item. ``instance`` arrives with its activity / city / event already
    set (or none, for a custom goal), and the fields follow its kind:

    - custom: title and details are required.
    - activity: pick one of the activity's dates (events) — that dates the item.
    - poi: tick the places to visit (POIs in the same cities), optionally name the goal.
    - city / event: neither.
    """

    class Meta:
        model = BucketListItem
        fields = [
            "custom_title", "custom_description", "event", "pois", "status", "priority",
            "target_date", "target_end_date", "target_season",
            "estimated_budget", "budget_currency", "with_who", "inspiration_source",
            "personal_notes", "categories", "is_public",
        ]
        labels = {
            "custom_title": "What do you want to do?", "custom_description": "Details",
            "event": "Which date?", "pois": "Places to visit",
            "target_date": "Target date (or first day)", "target_end_date": "Last day",
            "with_who": "With who", "inspiration_source": "Inspired by",
            "is_public": "Show on my public bucket list",
        }
        widgets = {
            "custom_title": forms.TextInput(attrs={**INPUT, "placeholder": "e.g. See the northern lights"}),
            "custom_description": forms.Textarea(attrs={**INPUT, "rows": 3}),
            "event": forms.Select(attrs=INPUT),
            "pois": forms.CheckboxSelectMultiple(attrs={"class": "sbl-check"}),
            "target_date": forms.DateInput(attrs={**INPUT, "type": "date"}, format="%Y-%m-%d"),
            "target_end_date": forms.DateInput(attrs={**INPUT, "type": "date"}, format="%Y-%m-%d"),
            "estimated_budget": forms.NumberInput(attrs={**INPUT, "step": "1", "min": "0"}),
            "budget_currency": forms.TextInput(attrs={**INPUT, "maxlength": 3}),
            "with_who": forms.TextInput(attrs=INPUT),
            "inspiration_source": forms.TextInput(attrs={**INPUT, "placeholder": "A friend, a film, a blog…"}),
            "personal_notes": forms.Textarea(attrs={**INPUT, "rows": 3}),
            "categories": forms.CheckboxSelectMultiple(attrs={"class": "sbl-check"}),
            "is_public": forms.CheckboxInput(attrs={"class": "sbl-check"}),
        }

    def __init__(self, *args, user, kind, pois=(), **kwargs):
        """``kind`` is the item's kind; ``pois`` the POIs a new POI item starts with."""
        super().__init__(*args, **kwargs)
        self.user = user
        self.kind = kind
        item = self.instance

        if kind == "custom":
            self.fields["custom_title"].required = True
        elif kind == "poi":
            self.fields["custom_title"].label = "Name this goal (optional)"
            self.fields["custom_title"].widget.attrs["placeholder"] = "e.g. Yellowstone's geysers"
            del self.fields["custom_description"]
        else:
            del self.fields["custom_title"]
            del self.fields["custom_description"]

        if kind == "activity":
            dates = Event.objects.visible_to(user).filter(related_activity=item.activity)
            if item.event_id:
                dates = dates | Event.objects.filter(pk=item.event_id)
            self.fields["event"].queryset = dates.order_by("start_date")
            self.fields["event"].empty_label = "No date yet"
            self.fields["event"].help_text = "Picking a date moves this from an idea to a dated plan."
        else:
            del self.fields["event"]

        if kind == "poi":
            chosen = list(item.pois.all()) if item.pk else list(pois)
            cities = {p.city_id for p in chosen}
            choices = POI.objects.filter(city_id__in=cities, approval_status=ApprovalStatus.APPROVED) | \
                POI.objects.filter(pk__in=[p.pk for p in chosen])
            self.fields["pois"].queryset = choices.select_related("city").order_by("city__name", "name").distinct()
            self.fields["pois"].label_from_instance = lambda p: f"{p.name} ({p.city.name})" if len(cities) > 1 else p.name
            self.fields["pois"].required = True
            if not item.pk:
                self.initial["pois"] = [p.pk for p in chosen]
        else:
            del self.fields["pois"]

        self.fields["categories"].queryset = BucketListCategory.objects.filter(user=user)
        self.fields["budget_currency"].required = False
        self.fields["target_season"].required = False  # model default "anytime"
        for name in ("status", "priority", "target_season"):
            self.fields[name].widget.attrs.setdefault("class", "sbl-input")

    def clean(self):
        cleaned = super().clean()
        cleaned["budget_currency"] = (cleaned.get("budget_currency") or "USD").upper()
        if not cleaned.get("target_season"):
            cleaned["target_season"] = BucketListItem._meta.get_field("target_season").get_default()
        return cleaned

    def save(self, commit=True):
        item = super().save(commit=False)
        if item.status == "completed" and not item.completed_date:
            from django.utils import timezone
            item.completed_date = timezone.now().date()
        if commit:
            item.save()
            self.save_m2m()
        return item


class CompleteItemForm(forms.Form):
    completed_date = forms.DateField(widget=forms.DateInput(attrs={**INPUT, "type": "date"}, format="%Y-%m-%d"))
    user_rating = forms.TypedChoiceField(
        choices=[("", "No rating")] + [(i, "★" * i) for i in range(5, 0, -1)],
        coerce=int, empty_value=None, required=False, label="Your rating",
        widget=forms.Select(attrs=INPUT),
    )
    completion_notes = forms.CharField(
        required=False, label="How was it?", widget=forms.Textarea(attrs={**INPUT, "rows": 4})
    )


class CategoryForm(forms.ModelForm):
    class Meta:
        model = BucketListCategory
        fields = ["name", "color", "icon", "description"]
        widgets = {
            "name": forms.TextInput(attrs={**INPUT, "placeholder": "e.g. Adventure goals"}),
            "color": forms.TextInput(attrs={"type": "color", "class": "h-10 w-16 cursor-pointer rounded-lg border border-warm-300"}),
            "icon": forms.TextInput(attrs={**INPUT, "placeholder": "🏔️ or bi-tree"}),
            "description": forms.TextInput(attrs=INPUT),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        clash = BucketListCategory.objects.filter(user=self.user, name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("You already have a category with that name.")
        return name


class PlanTripForm(forms.Form):
    """Start a trip from a bucket-list item: just enough to create it. Flights,
    lodging and the rest are added on the trip's own edit page afterwards."""

    name = forms.CharField(max_length=200, widget=forms.TextInput(attrs=INPUT))
    destination = forms.CharField(max_length=200, required=False, widget=forms.TextInput(attrs=INPUT))
    start_date = forms.DateField(label="First day", widget=forms.DateInput(attrs={**INPUT, "type": "date"}, format="%Y-%m-%d"))
    end_date = forms.DateField(label="Last day", widget=forms.DateInput(attrs={**INPUT, "type": "date"}, format="%Y-%m-%d"))

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "The last day is before the first day.")
        return cleaned
