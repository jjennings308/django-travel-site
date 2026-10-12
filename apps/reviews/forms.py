# reviews/forms.py
from django import forms

from .models import Review, ReviewReport

INPUT = {"class": "sbl-input"}


class ReviewForm(forms.ModelForm):
    rating = forms.TypedChoiceField(
        choices=[(i, "★" * i) for i in range(5, 0, -1)], coerce=int, label="Your rating",
        widget=forms.Select(attrs=INPUT),
    )

    class Meta:
        model = Review
        fields = ["rating", "title", "comment", "visit_date"]
        labels = {"title": "Headline (optional)", "comment": "Your review", "visit_date": "When were you there? (optional)"}
        help_texts = {"title": "", "comment": "", "visit_date": ""}
        widgets = {
            "title": forms.TextInput(attrs=INPUT),
            "comment": forms.Textarea(attrs={**INPUT, "rows": 5}),
            "visit_date": forms.DateInput(attrs={**INPUT, "type": "date"}, format="%Y-%m-%d"),
        }


class ReportForm(forms.ModelForm):
    class Meta:
        model = ReviewReport
        fields = ["reason", "details"]
        labels = {"details": "Anything else? (optional)"}
        widgets = {"reason": forms.Select(attrs=INPUT), "details": forms.Textarea(attrs={**INPUT, "rows": 3})}
