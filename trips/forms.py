# trips/forms.py
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Trip, TripBooking, TripActivity, TripDay
from locations.models import City, Country


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
    
    # Format as choices: (code, "CODE - Name")
    choices = []
    seen_codes = set()
    
    for code, name in currencies:
        if code and code not in seen_codes:
            seen_codes.add(code)
            if name:
                choices.append((code, f"{code} - {name}"))
            else:
                choices.append((code, code))
    
    # If no currencies in database, provide fallback list
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


class TripBaseForm(forms.ModelForm):
    """Base form with common trip fields"""
    
    # IMPORTANT: Explicitly declare currency as ChoiceField
    # This overrides the ModelForm's auto-generated CharField
    currency = forms.ChoiceField(
        choices=[],  # Will be populated in __init__
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=False
    )
    
    def __init__(self, *args, **kwargs):
        # Extract user from kwargs if provided
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Set currency choices dynamically from Country model
        self.fields['currency'].choices = get_currency_choices()
        
        # Set default currency based on user preferences
        if self.user and not self.instance.pk:  # Only for new trips
            default_currency = self._get_user_default_currency()
            if default_currency:
                self.fields['currency'].initial = default_currency
    
    def _get_user_default_currency(self):
        """
        Get the user's default currency from:
        1. AccountSettings.preferred_currency (if exists)
        2. Home country's currency (if exists)
        3. Falls back to 'USD'
        """
        if not self.user:
            return 'USD'
        
        # Try to get from AccountSettings
        try:
            if hasattr(self.user, 'settings') and self.user.settings.preferred_currency:
                return self.user.settings.preferred_currency
        except Exception:
            pass
        
        # Try to get from user's home country
        try:
            if hasattr(self.user, 'profile') and self.user.profile.home_country:
                home_country_name = self.user.profile.home_country
                country = Country.objects.filter(name__iexact=home_country_name).first()
                if country and country.currency_code:
                    return country.currency_code
        except Exception:
            pass
        
        # Default fallback
        return 'USD'
    
    class Meta:
        model = Trip
        fields = [
            'title', 'description', 'start_date', 'end_date',
            'primary_destination', 'countries', 'trip_type',
            'estimated_budget', 'currency', 'traveler_count',
            'privacy'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Summer Europe Adventure 2024'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Describe your trip...'
            }),
            'start_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'end_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'primary_destination': forms.Select(attrs={
                'class': 'form-select'
            }),
            'countries': forms.SelectMultiple(attrs={
                'class': 'form-select',
                'size': '5'
            }),
            'trip_type': forms.Select(attrs={
                'class': 'form-select'
            }),
            'estimated_budget': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0.00',
                'step': '0.01'
            }),
            # currency widget removed - defined as explicit field above
            'traveler_count': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1'
            }),
            'privacy': forms.Select(attrs={
                'class': 'form-select'
            })
        }
    
    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        
        if start_date and end_date:
            if end_date < start_date:
                raise ValidationError("End date must be after start date.")
        
        return cleaned_data


class PastTripForm(TripBaseForm):
    """Form for adding a trip that already occurred"""
    
    # Additional fields for past trips
    overall_rating = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=5,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Rate 1-5'
        })
    )
    trip_summary = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Share your experience...'
        })
    )
    highlights = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'What were the best moments?'
        })
    )
    actual_cost = forms.DecimalField(
        required=False,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Total spent',
            'step': '0.01'
        })
    )
    
    class Meta(TripBaseForm.Meta):
        fields = TripBaseForm.Meta.fields + [
            'overall_rating', 'trip_summary', 'highlights', 'actual_cost'
        ]
    
    def clean_start_date(self):
        start_date = self.cleaned_data.get('start_date')
        if start_date and start_date > timezone.now().date():
            raise ValidationError("Past trips must have a start date in the past.")
        return start_date
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.status = 'completed'  # Force status to completed for past trips
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class NewTripForm(TripBaseForm):
    """Form for planning a new upcoming trip"""
    
    # Planning-specific fields
    packing_list_items = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Enter items to pack (one per line)'
        }),
        help_text='Enter one item per line'
    )
    pre_trip_tasks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Tasks to complete before trip (one per line)'
        }),
        help_text='Enter one task per line'
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Any additional notes...'
        })
    )
    
    class Meta(TripBaseForm.Meta):
        fields = TripBaseForm.Meta.fields + [
            'packing_list_items', 'pre_trip_tasks', 'notes'
        ]
    
    def clean_start_date(self):
        start_date = self.cleaned_data.get('start_date')
        if start_date and start_date < timezone.now().date():
            raise ValidationError("New trips should have a future start date.")
        return start_date
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        
        # Set status to planning
        instance.status = 'planning'
        
        # Process packing list
        packing_items = self.cleaned_data.get('packing_list_items', '')
        if packing_items:
            instance.packing_list = [
                {'item': item.strip(), 'packed': False}
                for item in packing_items.split('\n')
                if item.strip()
            ]
        
        # Process pre-trip checklist
        pre_trip_items = self.cleaned_data.get('pre_trip_tasks', '')
        if pre_trip_items:
            instance.pre_trip_checklist = [
                {'task': task.strip(), 'completed': False}
                for task in pre_trip_items.split('\n')
                if task.strip()
            ]
        
        if commit:
            instance.save()
            self.save_m2m()
        
        return instance


class BookingForm(forms.ModelForm):
    """Form for creating a booking"""
    
    # IMPORTANT: Explicitly declare currency as ChoiceField
    currency = forms.ChoiceField(
        choices=[],  # Will be populated in __init__
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=False
    )
    
    def __init__(self, *args, **kwargs):
        # Extract user from kwargs if provided
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Set currency choices dynamically
        self.fields['currency'].choices = get_currency_choices()
        
        # Set default currency based on user preferences
        if self.user and not self.instance.pk:
            default_currency = self._get_user_default_currency()
            if default_currency:
                self.fields['currency'].initial = default_currency
    
    def _get_user_default_currency(self):
        """Same logic as TripBaseForm"""
        if not self.user:
            return 'USD'
        
        try:
            if hasattr(self.user, 'settings') and self.user.settings.preferred_currency:
                return self.user.settings.preferred_currency
        except Exception:
            pass
        
        try:
            if hasattr(self.user, 'profile') and self.user.profile.home_country:
                home_country_name = self.user.profile.home_country
                country = Country.objects.filter(name__iexact=home_country_name).first()
                if country and country.currency_code:
                    return country.currency_code
        except Exception:
            pass
        
        return 'USD'
    
    class Meta:
        model = TripBooking
        fields = [
            'booking_type', 'title', 'description',
            'start_date', 'end_date', 'start_time',
            'vendor', 'cost', 'currency',
            'confirmation_number', 'booking_url',
            'payment_status', 'cancellation_policy',
            'is_refundable', 'notes'
        ]
        widgets = {
            'booking_type': forms.Select(attrs={'class': 'form-select'}),
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Flight to Paris'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3
            }),
            'start_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'end_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'start_time': forms.TimeInput(attrs={
                'class': 'form-control',
                'type': 'time'
            }),
            'vendor': forms.Select(attrs={'class': 'form-select'}),
            'cost': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01'
            }),
            # currency widget removed - defined as explicit field above
            'confirmation_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Confirmation #'
            }),
            'booking_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://...'
            }),
            'payment_status': forms.Select(attrs={'class': 'form-select'}),
            'cancellation_policy': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2
            }),
            'is_refundable': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3
            })
        }


class QuickBookFlightForm(forms.Form):
    """Quick form for booking flights via API"""
    
    origin = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Departure city or airport code'
        })
    )
    destination = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Arrival city or airport code'
        })
    )
    departure_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    return_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    passengers = forms.IntegerField(
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control'
        })
    )
    cabin_class = forms.ChoiceField(
        choices=[
            ('economy', 'Economy'),
            ('premium_economy', 'Premium Economy'),
            ('business', 'Business'),
            ('first', 'First Class')
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )


class QuickBookHotelForm(forms.Form):
    """Quick form for booking hotels via API"""
    
    destination = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'City or hotel name'
        })
    )
    check_in = forms.DateField(
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    check_out = forms.DateField(
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    rooms = forms.IntegerField(
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control'
        })
    )
    guests = forms.IntegerField(
        min_value=1,
        initial=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control'
        })
    )
    max_price = forms.DecimalField(
        required=False,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Max price per night',
            'step': '0.01'
        })
    )


class TripReviewForm(forms.Form):
    """Form for reviewing/commenting on a completed trip"""
    
    overall_rating = forms.IntegerField(
        min_value=1,
        max_value=5,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Rate 1-5 stars'
        })
    )
    trip_summary = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 5,
            'placeholder': 'Share your overall experience...'
        })
    )
    highlights = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'What were the best moments?'
        })
    )
    would_recommend = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        })
    )
    tips_for_others = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Any advice for future travelers?'
        })
    )
    
    def save(self, trip):
        """Update the trip with review data"""
        trip.overall_rating = self.cleaned_data['overall_rating']
        trip.trip_summary = self.cleaned_data['trip_summary']
        trip.highlights = self.cleaned_data['highlights']
        
        # Add tips to notes if provided
        tips = self.cleaned_data.get('tips_for_others')
        if tips:
            trip.notes = f"{trip.notes}\n\nTips for travelers:\n{tips}".strip()
        
        trip.status = 'completed'
        trip.save()
        return trip


class UpdateTripStatusForm(forms.Form):
    """Form for updating trip status"""
    
    status = forms.ChoiceField(
        choices=Trip.STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Optional notes about status change...'
        })
    )
