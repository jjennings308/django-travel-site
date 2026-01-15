# accounts/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from .models import User, Profile, TravelPreferences, AccountSettings
from datetime import datetime
from zoneinfo import available_timezones, ZoneInfo

COMMON_TIMEZONES = [
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "UTC",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
]

def timezone_choices_grouped():
    all_tzs = sorted(available_timezones())
    common = [(tz, tz) for tz in COMMON_TIMEZONES if tz in all_tzs]
    remaining = [(tz, tz) for tz in all_tzs if tz not in COMMON_TIMEZONES]
    return [
        ("Common Timezones", common),
        ("All Timezones", remaining),
    ]


class UserRegistrationForm(UserCreationForm):
    """Form for user registration using email as username"""
    
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Email address'
        })
    )
    
    first_name = forms.CharField(
        required=True,
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'First name'
        })
    )
    
    last_name = forms.CharField(
        required=True,
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Last name'
        })
    )
    
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password'
        })
    )
    
    password2 = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm password'
        })
    )
    
    terms_accepted = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        error_messages={
            'required': 'You must accept the terms and conditions to register.'
        }
    )
    
    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'password1', 'password2']
    
    def clean_email(self):
        """Validate that email is unique"""
        email = self.cleaned_data.get('email')
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('An account with this email already exists.')
        return email.lower()
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        # Username will be set to email in the view
        if commit:
            user.save()
        return user


class ProfileForm(forms.ModelForm):
    """Form for editing user profile"""
    
    class Meta:
        model = Profile
        fields = [
            'bio', 'avatar', 'cover_photo',
            'home_country', 'home_city', 'current_location',
            'website', 'instagram', 'twitter'
        ]
        widgets = {
            'bio': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Tell us about yourself...'
            }),
            'home_country': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., United States'
            }),
            'home_city': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., New York'
            }),
            'current_location': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Where are you now?'
            }),
            'website': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://...'
            }),
            'instagram': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '@username'
            }),
            'twitter': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '@username'
            }),
        }


class TravelPreferencesForm(forms.ModelForm):
    """Form for editing travel preferences (shown on profile)"""

    travel_styles = forms.MultipleChoiceField(
        choices=TravelPreferences.TRAVEL_STYLE_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Select all that apply.",
    )

    class Meta:
        model = TravelPreferences
        fields = [
            "budget_preference",
            "travel_styles",
            "travel_pace",
            "fitness_level",
            "mobility_restrictions",
        ]
        widgets = {
            "budget_preference": forms.Select(attrs={"class": "form-control"}),
            "travel_pace": forms.Select(attrs={"class": "form-control"}),
            "fitness_level": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Travel styles initial from JSON list
        existing = getattr(self.instance, "travel_styles", None) or []
        if isinstance(existing, str):
            existing = [existing]
        self.initial.setdefault("travel_styles", existing)

    def clean_travel_styles(self):
        values = self.cleaned_data.get("travel_styles") or []
        # Validate against allowed keys
        allowed = {k for k, _ in TravelPreferences.TRAVEL_STYLE_CHOICES}
        bad = [v for v in values if v not in allowed]
        if bad:
            raise ValidationError(f"Invalid travel style(s): {', '.join(bad)}")

        # Normalize: dedupe + keep order as defined in choices
        choice_order = [k for k, _ in TravelPreferences.TRAVEL_STYLE_CHOICES]
        values_set = set(values)
        normalized = [k for k in choice_order if k in values_set]
        return normalized

    def save(self, commit=True):
        self.instance.travel_styles = self.cleaned_data.get("travel_styles") or []
        return super().save(commit=commit)


class AccountSettingsForm(forms.ModelForm):
    """Form for editing account settings (notifications, regional, privacy)"""

    timezone = forms.ChoiceField(
        choices=[],
        required=True,
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    class Meta:
        model = AccountSettings
        fields = [
            # Notifications
            "email_notifications",
            "push_notifications",
            "marketing_emails",
            "notify_bucket_list_reminders",
            "notify_trip_updates",
            "notify_event_reminders",
            "notify_friend_activity",
            "notify_recommendations",
            # Regional
            "language",
            "units",
            "preferred_currency",
            "timezone",
            "theme",
            # Privacy
            "show_email_on_profile",
            "show_trips_publicly",
            "allow_friend_requests",
        ]
        widgets = {
            "language": forms.Select(attrs={"class": "form-control"}),
            "units": forms.Select(attrs={"class": "form-control"}),
            "preferred_currency": forms.Select(attrs={"class": "form-control"}),
            "theme": forms.Select(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Timezone dropdown
        self.fields["timezone"].choices = timezone_choices_grouped()
        current_tz = (getattr(self.instance, "timezone", None) or "UTC")
        self.initial.setdefault("timezone", current_tz)
        try:
            now_local = datetime.now(ZoneInfo(current_tz)).strftime("%a %b %d, %Y %I:%M %p")
            self.fields["timezone"].help_text = f"Current local time: {now_local}"
        except Exception:
            pass

    def save(self, commit=True):
        self.instance.timezone = self.cleaned_data["timezone"]
        return super().save(commit=commit)
