# bucketlists/forms.py
from django import forms

from .models import BucketListCategory, BucketListItem

INPUT = {"class": "sbl-input"}


class BucketListItemForm(forms.ModelForm):
    """Add/edit an item. For an item linked to an activity, city, place or event the
    title comes from that object, so the custom title/description fields are dropped."""

    class Meta:
        model = BucketListItem
        fields = [
            "custom_title", "custom_description", "status", "priority", "target_date", "target_season",
            "estimated_budget", "budget_currency", "with_who", "inspiration_source",
            "personal_notes", "categories", "is_public",
        ]
        labels = {
            "custom_title": "What do you want to do?", "custom_description": "Details",
            "with_who": "With who", "inspiration_source": "Inspired by",
            "is_public": "Show on my public bucket list",
        }
        widgets = {
            "custom_title": forms.TextInput(attrs={**INPUT, "placeholder": "e.g. See the northern lights"}),
            "custom_description": forms.Textarea(attrs={**INPUT, "rows": 3}),
            "target_date": forms.DateInput(attrs={**INPUT, "type": "date"}, format="%Y-%m-%d"),
            "estimated_budget": forms.NumberInput(attrs={**INPUT, "step": "1", "min": "0"}),
            "budget_currency": forms.TextInput(attrs={**INPUT, "maxlength": 3}),
            "with_who": forms.TextInput(attrs=INPUT),
            "inspiration_source": forms.TextInput(attrs={**INPUT, "placeholder": "A friend, a film, a blog…"}),
            "personal_notes": forms.Textarea(attrs={**INPUT, "rows": 3}),
            "categories": forms.CheckboxSelectMultiple(attrs={"class": "sbl-check"}),
            "is_public": forms.CheckboxInput(attrs={"class": "sbl-check"}),
        }

    def __init__(self, *args, user, linked=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.linked = linked
        if linked:
            del self.fields["custom_title"]
            del self.fields["custom_description"]
        else:
            self.fields["custom_title"].required = True
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
