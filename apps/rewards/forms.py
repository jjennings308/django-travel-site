# ============================================
# rewards/forms.py
# ============================================
from django import forms
from django.core.exceptions import ValidationError
from .models import RewardsProgramType


class RewardsProgramSearchForm(forms.Form):
    """Form for filtering/searching rewards programs"""
    
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'sbl-input',
            'placeholder': 'Search programs...'
        })
    )
    
    program_type = forms.ChoiceField(
        required=False,
        choices=[('', 'All Types')] + list(RewardsProgramType.choices),
        widget=forms.Select(attrs={'class': 'sbl-input'})
    )
