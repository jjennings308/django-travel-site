# ============================================
# rewards/forms.py
# ============================================
from django import forms
from django.core.exceptions import ValidationError
from .models import RewardsProgram, UserRewardsMembership, RewardsProgramType


class UserRewardsMembershipForm(forms.ModelForm):
    """Form for adding/editing rewards program memberships"""
    
    class Meta:
        model = UserRewardsMembership
        fields = [
            'program',
            'member_number',
            'member_name',
            'current_tier',
            'points_balance',
            'tier_expires',
            'username',
            'is_primary',
            'notes',
            'show_on_profile',
            'notify_on_expiration',
            'expiration_notice_days',
        ]
        widgets = {
            'program': forms.Select(attrs={
                'class': 'form-control'
            }),
            'member_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Membership number'
            }),
            'member_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Name on account (optional)'
            }),
            'current_tier': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Gold, Platinum'
            }),
            'points_balance': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Current balance (optional)',
                'min': 0
            }),
            'tier_expires': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Login username (optional)'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Any notes about this membership...'
            }),
            'expiration_notice_days': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1
            }),
        }
    
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        
        # Only show active programs
        self.fields['program'].queryset = RewardsProgram.objects.filter(
            is_active=True
        )
        
        # Group programs by type for better UX
        choices = [('', '---------')]
        for prog_type in RewardsProgramType:
            programs = RewardsProgram.objects.filter(
                is_active=True,
                program_type=prog_type.value
            )
            if programs.exists():
                group_choices = [(p.id, str(p)) for p in programs]
                choices.append((prog_type.label, group_choices))
        
        self.fields['program'].choices = choices
        
        # If editing, check if user already has this program
        if self.instance and self.instance.pk:
            existing_programs = UserRewardsMembership.objects.filter(
                user=self.user
            ).exclude(pk=self.instance.pk).values_list('program_id', flat=True)
        else:
            existing_programs = UserRewardsMembership.objects.filter(
                user=self.user
            ).values_list('program_id', flat=True)
        
        # Disable programs user already has
        if existing_programs:
            self.fields['program'].help_text = (
                "Note: Programs you're already enrolled in are not shown."
            )
            self.fields['program'].queryset = self.fields['program'].queryset.exclude(
                id__in=existing_programs
            )
    
    def clean(self):
        cleaned_data = super().clean()
        
        # Validate user doesn't already have this program
        program = cleaned_data.get('program')
        if program and self.user:
            existing = UserRewardsMembership.objects.filter(
                user=self.user,
                program=program
            )
            if self.instance and self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            
            if existing.exists():
                raise ValidationError(
                    f"You already have a membership for {program.name}."
                )
        
        return cleaned_data
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.user = self.user
        
        if commit:
            instance.save()
        return instance


class QuickAddRewardsForm(forms.Form):
    """Quick form to add common rewards programs"""
    
    program = forms.ModelChoiceField(
        queryset=RewardsProgram.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Program"
    )
    
    member_number = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Membership number'
        })
    )
    
    current_tier = forms.CharField(
        required=False,
        max_length=50,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Tier (optional)'
        })
    )
    
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        
        if user:
            # Exclude programs user already has
            existing_programs = UserRewardsMembership.objects.filter(
                user=user
            ).values_list('program_id', flat=True)
            
            self.fields['program'].queryset = self.fields['program'].queryset.exclude(
                id__in=existing_programs
            )


class RewardsProgramSearchForm(forms.Form):
    """Form for filtering/searching rewards programs"""
    
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search programs...'
        })
    )
    
    program_type = forms.ChoiceField(
        required=False,
        choices=[('', 'All Types')] + list(RewardsProgramType.choices),
        widget=forms.Select(attrs={'class': 'form-control'})
    )
