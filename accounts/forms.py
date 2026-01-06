# accounts/forms.py
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

User = get_user_model()

class SignUpForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "username", "first_name", "last_name")

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("That email is already in use.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = user.email.strip().lower()
        user.is_active = False          # IMPORTANT: require email verification
        user.is_verified = False
        if commit:
            user.save()
        return user
    
class AdminUserCreateForm(UserCreationForm):
    """
    Admin-only 'Add User' form.
    Uses your custom User model (email is unique/required).
    """
    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "email",
            "username",
            "first_name",
            "last_name",
            "phone_number",
            "date_of_birth",
            "is_staff",
            "is_superuser",
            "is_active",
            "is_verified",
            "is_premium",
            "profile_visibility",
        )

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("That email is already in use.")
        return email
