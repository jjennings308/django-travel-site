# pages/forms.py
from django import forms

INPUT = {"class": "sbl-input"}


class ContactForm(forms.Form):
    name = forms.CharField(max_length=100, widget=forms.TextInput(attrs=INPUT))
    email = forms.EmailField(label="Your email", widget=forms.EmailInput(attrs=INPUT))
    subject = forms.CharField(max_length=150, widget=forms.TextInput(attrs=INPUT))
    message = forms.CharField(max_length=5000, widget=forms.Textarea(attrs={**INPUT, "rows": 6}))
    # Honeypot: hidden from people, filled in by simple bots.
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))
