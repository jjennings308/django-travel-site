# accounts/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from datetime import datetime
from zoneinfo import available_timezones, ZoneInfo
from .models import (
    User, Profile, TravelPreferences, AccountSettings, RoleRequest
)
from locations.models import Country

def get_currency_choices():
    """
    Dynamically generate currency choices from the Country model.
    Returns a list of tuples (currency_code, display_name).
    """
    # Get all unique currencies from countries
    currencies = Country.objects.exclude(
        currency_code=''
    ).values_list(
        'currency_code', 'currency_name'
    ).distinct().order_by('currency_code')
    
    # Format as choices
    choices = []
    seen_codes = set()
    
    for code, name in currencies:
        if code and code not in seen_codes:
            seen_codes.add(code)
            if name:
                choices.append((code, f"{code} - {name}"))
            else:
                choices.append((code, code))
    
    # Fallback if database is empty
    if not choices:
        choices = [
            ('USD', 'USD - US Dollar'),
            ('EUR', 'EUR - Euro'),
            ('GBP', 'GBP - British Pound'),
            ('JPY', 'JPY - Japanese Yen'),
            ('AUD', 'AUD - Australian Dollar'),
            ('CAD', 'CAD - Canadian Dollar'),
        ]
    
    return choices


class AccountSettingsForm(forms.ModelForm):
    """Form for user account settings"""
    
    # Override preferred_currency to add dynamic choices
    preferred_currency = forms.ChoiceField(
        label='Preferred Currency',
        help_text='Your default currency for budgets and expenses',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Populate currency choices from Country model
        self.fields['preferred_currency'].choices = get_currency_choices()
    
    class Meta:
        model = AccountSettings
        fields = [
            'email_notifications',
            'push_notifications',
            'marketing_emails',
            'notify_bucket_list_reminders',
            'notify_trip_updates',
            'notify_event_reminders',
            'notify_friend_activity',
            'notify_recommendations',
            'language',
            'units',
            'preferred_currency',
            'timezone',
            'theme',
            'show_email_on_profile',
            'show_trips_publicly',
            'allow_friend_requests',
        ]
        widgets = {
            'email_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'push_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'marketing_emails': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_bucket_list_reminders': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_trip_updates': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_event_reminders': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_friend_activity': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_recommendations': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'language': forms.Select(attrs={'class': 'form-select'}),
            'units': forms.Select(attrs={'class': 'form-select'}),
            'timezone': forms.TextInput(attrs={'class': 'form-control'}),
            'theme': forms.Select(attrs={'class': 'form-select'}),
            'show_email_on_profile': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_trips_publicly': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_friend_requests': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class ProfileForm(forms.ModelForm):
    """Form for user profile"""
    
    class Meta:
        model = Profile
        fields = [
            'bio',
            'avatar',
            'cover_photo',
            'home_country',
            'home_city',
            'current_location',
            'website',
            'instagram',
            'twitter',
        ]
        widgets = {
            'bio': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Tell us about yourself...'
            }),
            'avatar': forms.FileInput(attrs={'class': 'form-control'}),
            'cover_photo': forms.FileInput(attrs={'class': 'form-control'}),
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
                'placeholder': 'https://'
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
    """Form for travel preferences"""
    
    class Meta:
        model = TravelPreferences
        fields = [
            'budget_preference',
            'travel_styles',
            'travel_pace',
            'preferred_activities',
            'fitness_level',
            'mobility_restrictions',
        ]
        widgets = {
            'budget_preference': forms.Select(attrs={'class': 'form-select'}),
            'travel_styles': forms.CheckboxSelectMultiple(),
            'travel_pace': forms.Select(attrs={'class': 'form-select'}),
            'preferred_activities': forms.CheckboxSelectMultiple(),
            'fitness_level': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
                'max': 5
            }),
            'mobility_restrictions': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

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
    """Form for user registration with username and email"""
    
    username = forms.CharField(
        required=True,
        max_length=30,
        validators=[
            RegexValidator(
                r'^[a-zA-Z0-9_]+$',
                'Username can only contain letters, numbers, and underscores'
            )
        ],
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Username (letters, numbers, and _ only)'
        }),
        help_text='Your unique username for your profile URL'
    )
    
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
    
    # Optional role requests during registration
    request_vendor_role = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label='I want to apply to become a vendor',
        help_text='Your account will be created immediately, but vendor features require approval'
    )
    
    request_content_provider_role = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label='I want to apply to become a content provider',
        help_text='Your account will be created immediately, but content provider features require approval'
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
        fields = ['username', 'email', 'first_name', 'last_name', 'password1', 'password2']
    
    def clean_username(self):
        """Validate that username is unique (case-insensitive)"""
        username = self.cleaned_data.get('username')
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError('This username is already taken.')
        return username.lower()
    
    def clean_email(self):
        """Validate that email is unique (case-insensitive)"""
        email = self.cleaned_data.get('email')
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('An account with this email already exists.')
        return email.lower()
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.username = self.cleaned_data['username']
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


class RoleRequestForm(forms.ModelForm):
    """Form for requesting vendor or content provider role"""
    
    class Meta:
        model = RoleRequest
        fields = [
            'requested_role',
            'business_name',
            'business_description',
            'website',
            'business_license',
            'supporting_documents',
        ]
        widgets = {
            'requested_role': forms.Select(attrs={'class': 'form-control'}),
            'business_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Your business or brand name'
            }),
            'business_description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': 'Tell us about your business, experience, and why you want this role...'
            }),
            'website': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://your-website.com (optional)'
            }),
            'business_license': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'License number (if applicable)'
            }),
            'supporting_documents': forms.FileInput(attrs={
                'class': 'form-control'
            }),
        }
    
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        
        # Make business_description required
        self.fields['business_description'].required = True
        
    def clean(self):
        cleaned_data = super().clean()
        requested_role = cleaned_data.get('requested_role')
        
        # Check if user already has this role
        if self.user:
            if requested_role == RoleRequest.RequestedRole.VENDOR and self.user.is_vendor:
                raise ValidationError('You already have vendor access.')
            elif requested_role == RoleRequest.RequestedRole.CONTENT_PROVIDER and self.user.is_content_provider:
                raise ValidationError('You already have content provider access.')
        
        return cleaned_data


class RoleRequestReviewForm(forms.Form):
    """Form for staff to review role requests"""
    
    action = forms.ChoiceField(
        choices=[
            ('approve', 'Approve'),
            ('reject', 'Reject'),
        ],
        widget=forms.RadioSelect
    )
    
    review_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Internal notes (optional)'
        }),
        label='Internal Notes'
    )
    
    rejection_reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Reason for rejection (shown to user)'
        }),
        label='Rejection Reason (if rejecting)'
    )
    
    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get('action')
        rejection_reason = cleaned_data.get('rejection_reason')
        
        if action == 'reject' and not rejection_reason:
            raise ValidationError('You must provide a rejection reason when rejecting a request.')
        
        return cleaned_data
