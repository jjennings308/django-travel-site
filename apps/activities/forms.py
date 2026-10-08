# activities/forms.py
from django import forms
from django.utils import timezone
from .models import Activity, ActivityCategory, ActivityTag
from apps.approval_system.models import ApprovalStatus
from apps.locations.models import City, Country, Region
from apps.locations.widgets import CountryTaggedSelect

PLACE_AND_TIMING_FIELDS = ['country', 'region', 'city', 'recurrence', 'usual_months']


class PlaceAndTimingMixin:
    """Where (country / region / city, filtered by country in the browser) and how
    often (recurrence + usual months) for the activity forms."""

    def setup_place_and_timing(self):
        # Built here, not declared on the class: a plain mixin's declared fields are
        # not collected by the form metaclass.
        self.fields['usual_months'] = forms.TypedMultipleChoiceField(
            choices=Activity.MONTHS, coerce=int, required=False, label="Usual months",
            widget=forms.CheckboxSelectMultiple(attrs={'class': 'sbl-check'}),
        )
        approved = {'approval_status': ApprovalStatus.APPROVED}
        self.fields['country'].queryset = Country.objects.filter(**approved).order_by('name')
        self.fields['region'].queryset = Region.objects.order_by('name')
        self.fields['city'].queryset = City.objects.filter(**approved).order_by('name')
        self.fields['country'].widget.attrs['class'] = 'sbl-input'
        for name in ('region', 'city'):
            self.fields[name].widget = CountryTaggedSelect(attrs={'class': 'sbl-input'})
            self.fields[name].widget.choices = self.fields[name].choices
        self.fields['recurrence'].widget.attrs['class'] = 'sbl-input'
        self.fields['suggested_location'].label = 'Or a place not in our list'
        self.fields['suggested_timeframe'].label = 'Timing notes'
        for name in PLACE_AND_TIMING_FIELDS:
            self.fields[name].required = False
        if self.instance.pk:
            self.initial['usual_months'] = self.instance.usual_months or []

    def clean(self):
        cleaned = super().clean()
        country, region, city = (cleaned.get(k) for k in ('country', 'region', 'city'))
        if city and country and city.country_id != country.pk:
            self.add_error('city', f"{city.name} is not in {country.name}.")
        if region and country and region.country_id != country.pk:
            self.add_error('region', f"{region.name} is not in {country.name}.")
        if city and region and city.region_id and city.region_id != region.pk:
            self.add_error('region', f"{city.name} is in {city.region.name}.")
        if not cleaned.get('recurrence'):
            cleaned['recurrence'] = 'anytime'
        cleaned['usual_months'] = sorted(set(cleaned.get('usual_months') or []))
        return cleaned


class ActivityCreateForm(PlaceAndTimingMixin, forms.ModelForm):
    """Form for users to create their own activities"""
    
    # Allow users to add tags
    tags = forms.ModelMultipleChoiceField(
        queryset=ActivityTag.objects.filter(user_can_add=True),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Select tags that describe this activity"
    )
    
    class Meta:
        model = Activity
        fields = [
            'category',
            'name',
            'description',
            'visibility',
            'specificity_level',
            'country',
            'region',
            'city',
            'suggested_location',
            'recurrence',
            'usual_months',
            'suggested_timeframe',
            'suggested_date_range_start',
            'suggested_date_range_end',
            'skill_level',
            'fitness_required',
            'age_minimum',
            'age_maximum',
            'typical_duration',
            'duration_category',
            'cost_level',
            'estimated_cost_min',
            'estimated_cost_max',
            'best_for',
            'best_season',
            'indoor_outdoor',
            'equipment_needed',
            'booking_required',
            'guide_required',
            'wheelchair_accessible',
            'suitable_for_children',
            'risk_level',
            'safety_notes',
        ]
        
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'sbl-input',
                'placeholder': 'E.g., "See Kenny Chesney concert at Vegas Sphere"'
            }),
            'category': forms.Select(attrs={
                'class': 'sbl-input'
            }),
            'description': forms.Textarea(attrs={
                'class': 'sbl-input',
                'rows': 6,
                'placeholder': 'Describe this activity in detail. What makes it special? What should people know?'
            }),
            'visibility': forms.Select(attrs={
                'class': 'sbl-input'
            }),
            'specificity_level': forms.Select(attrs={
                'class': 'sbl-input'
            }),
            'suggested_location': forms.TextInput(attrs={
                'class': 'sbl-input',
                'placeholder': 'E.g., "Las Vegas, Nevada"'
            }),
            'suggested_timeframe': forms.TextInput(attrs={
                'class': 'sbl-input',
                'placeholder': 'E.g., "Summer 2026" or "Weekends in April"'
            }),
            'suggested_date_range_start': forms.DateInput(attrs={
                'class': 'sbl-input',
                'type': 'date'
            }),
            'suggested_date_range_end': forms.DateInput(attrs={
                'class': 'sbl-input',
                'type': 'date'
            }),
            'skill_level': forms.Select(attrs={
                'class': 'sbl-input'
            }),
            'fitness_required': forms.NumberInput(attrs={
                'class': 'sbl-input',
                'min': 1,
                'max': 5
            }),
            'age_minimum': forms.NumberInput(attrs={
                'class': 'sbl-input'
            }),
            'age_maximum': forms.NumberInput(attrs={
                'class': 'sbl-input'
            }),
            'typical_duration': forms.NumberInput(attrs={
                'class': 'sbl-input',
                'placeholder': 'Duration in minutes'
            }),
            'duration_category': forms.Select(attrs={
                'class': 'sbl-input'
            }),
            'cost_level': forms.Select(attrs={
                'class': 'sbl-input'
            }),
            'estimated_cost_min': forms.NumberInput(attrs={
                'class': 'sbl-input',
                'step': '0.01',
                'placeholder': '$'
            }),
            'estimated_cost_max': forms.NumberInput(attrs={
                'class': 'sbl-input',
                'step': '0.01',
                'placeholder': '$'
            }),
            'best_for': forms.Select(attrs={
                'class': 'sbl-input'
            }),
            'best_season': forms.TextInput(attrs={
                'class': 'sbl-input',
                'placeholder': 'e.g., ["spring", "summer"]'
            }),
            'indoor_outdoor': forms.Select(attrs={
                'class': 'sbl-input'
            }),
            'equipment_needed': forms.Textarea(attrs={
                'class': 'sbl-input',
                'rows': 3,
                'placeholder': 'List any equipment or gear needed'
            }),
            'booking_required': forms.CheckboxInput(attrs={
                'class': 'sbl-check'
            }),
            'guide_required': forms.CheckboxInput(attrs={
                'class': 'sbl-check'
            }),
            'wheelchair_accessible': forms.CheckboxInput(attrs={
                'class': 'sbl-check'
            }),
            'suitable_for_children': forms.CheckboxInput(attrs={
                'class': 'sbl-check'
            }),
            'risk_level': forms.Select(attrs={
                'class': 'sbl-input'
            }),
            'safety_notes': forms.Textarea(attrs={
                'class': 'sbl-input',
                'rows': 3,
                'placeholder': 'Any safety considerations people should know about'
            }),
        }
        
        help_texts = {
            'visibility': 'Private activities are only visible to you. Public activities require approval from our team.',
            'specificity_level': 'How detailed is your activity description?',
            'category': 'Choose the category that best fits this activity',
        }
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.setup_place_and_timing()
        
        # Filter categories to only those that allow user submissions
        self.fields['category'].queryset = ActivityCategory.objects.filter(
            is_active=True,
            allow_user_submissions=True
        )
        
        # Make some fields optional for quick creation
        optional_fields = [
            'country',
            'region',
            'city',
            'suggested_location',
            'recurrence',
            'usual_months',
            'suggested_timeframe',
            'suggested_date_range_start',
            'suggested_date_range_end',
            'age_minimum',
            'age_maximum',
            'typical_duration',
            'estimated_cost_min',
            'estimated_cost_max',
            'equipment_needed',
            'safety_notes',
            'wheelchair_accessible',
            'suitable_for_children',
            'best_season',  # Make this optional too
            'risk_level',
        ]
        
        for field in optional_fields:
            if field in self.fields:
                self.fields[field].required = False
    
    def clean_best_season(self):
        """Handle best_season field - convert to list if needed"""
        value = self.cleaned_data.get('best_season')
        if not value:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            # If user entered a string, try to parse it
            if value.strip() == '':
                return []
            # Simple parsing - just return as list with one item
            return [value.strip()]
        return []
    
    def save(self, commit=True):
        activity = super().save(commit=False)
        
        # Set the creator
        if self.user:
            activity.created_by = self.user
            activity.source = 'staff' if self.user.is_staff else 'user'
        
        # If user selected public visibility, set to pending
        if activity.visibility == 'public':
            activity.approval_status = ApprovalStatus.PENDING
            activity.submitted_by = self.user
            activity.submitted_at = timezone.now()
        else:
            # Private activities stay as draft
            activity.approval_status = ApprovalStatus.DRAFT
        
        # Staff can bypass approval
        if self.user and self.user.is_staff and activity.visibility == 'public':
            activity.approval_status = ApprovalStatus.APPROVED
        
        if commit:
            activity.save()
            
            # Handle tags
            if 'tags' in self.cleaned_data:
                activity.tags.set(self.cleaned_data['tags'])
        
        return activity


class ActivityEditForm(PlaceAndTimingMixin, forms.ModelForm):
    """Form for editing existing activities"""
    
    tags = forms.ModelMultipleChoiceField(
        queryset=ActivityTag.objects.filter(user_can_add=True),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Select tags that describe this activity"
    )
    
    class Meta:
        model = Activity
        fields = [
            'category',
            'name',
            'description',
            'specificity_level',
            'country',
            'region',
            'city',
            'suggested_location',
            'recurrence',
            'usual_months',
            'suggested_timeframe',
            'suggested_date_range_start',
            'suggested_date_range_end',
            'skill_level',
            'fitness_required',
            'age_minimum',
            'age_maximum',
            'typical_duration',
            'duration_category',
            'cost_level',
            'estimated_cost_min',
            'estimated_cost_max',
            'best_for',
            'best_season',
            'indoor_outdoor',
            'equipment_needed',
            'booking_required',
            'guide_required',
            'wheelchair_accessible',
            'suitable_for_children',
            'risk_level',
            'safety_notes',
        ]
        
        widgets = {
            'name': forms.TextInput(attrs={'class': 'sbl-input'}),
            'category': forms.Select(attrs={'class': 'sbl-input'}),
            'description': forms.Textarea(attrs={'class': 'sbl-input', 'rows': 6}),
            'equipment_needed': forms.Textarea(attrs={'class': 'sbl-input', 'rows': 3}),
            'safety_notes': forms.Textarea(attrs={'class': 'sbl-input', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup_place_and_timing()
        
        # Set initial tags
        if self.instance and self.instance.pk:
            self.fields['tags'].initial = self.instance.tags.filter(user_can_add=True)
    
    def save(self, commit=True):
        activity = super().save(commit=False)
        
        if commit:
            activity.save()
            
            # Handle tags
            if 'tags' in self.cleaned_data:
                activity.tags.set(self.cleaned_data['tags'])
        
        return activity


class ActivityQuickCreateForm(forms.ModelForm):
    """Simplified form for quick activity creation"""
    
    class Meta:
        model = Activity
        fields = [
            'category',
            'name',
            'description',
            'visibility',
        ]
        
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'sbl-input',
                'placeholder': 'What do you want to do?'
            }),
            'category': forms.Select(attrs={
                'class': 'sbl-input'
            }),
            'description': forms.Textarea(attrs={
                'class': 'sbl-input',
                'rows': 4,
                'placeholder': 'Briefly describe this activity'
            }),
            'visibility': forms.Select(attrs={
                'class': 'sbl-input'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Filter categories
        self.fields['category'].queryset = ActivityCategory.objects.filter(
            is_active=True,
            allow_user_submissions=True
        )
    
    def save(self, commit=True):
        activity = super().save(commit=False)
        
        # Set the creator
        if self.user:
            activity.created_by = self.user
            activity.source = 'staff' if self.user.is_staff else 'user'
        
        # Set defaults
        activity.specificity_level = 'general'
        activity.skill_level = 'any'
        activity.cost_level = 'varies'
        activity.duration_category = 'varies'
        activity.best_for = 'any'
        activity.indoor_outdoor = 'either'
        activity.best_season = []  # Empty list
        
        # Handle approval
        if activity.visibility == 'public':
            activity.approval_status = ApprovalStatus.PENDING
            activity.submitted_by = self.user
            activity.submitted_at = timezone.now()
            
            # Staff bypass
            if self.user and self.user.is_staff:
                activity.approval_status = ApprovalStatus.APPROVED
        else:
            activity.approval_status = ApprovalStatus.DRAFT
        
        if commit:
            activity.save()
        
        return activity
