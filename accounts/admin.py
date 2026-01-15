# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.translation import gettext_lazy as _
from django import forms
from datetime import datetime
from zoneinfo import available_timezones, ZoneInfo

from .models import User, Profile, TravelPreferences, AccountSettings

COMMON_TIMEZONES = [
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "Europe/London",
    "Europe/Rome",
    "Europe/Paris",
    "Europe/Berlin",
    "Asia/Tokyo",
    "Asia/Shanghai",
    "Asia/Hong_Kong",
    "Australia/Sydney",
]

def timezone_choices_grouped():
    all_tzs = sorted(available_timezones())
    common = [(tz, tz) for tz in COMMON_TIMEZONES if tz in all_tzs]
    remaining = [(tz, tz) for tz in all_tzs if tz not in COMMON_TIMEZONES]
    return [
        ("Common Timezones", common),
        ("All Timezones", remaining),
    ]


class AccountSettingsAdminForm(forms.ModelForm):
    timezone = forms.ChoiceField(choices=[], required=True)

    class Meta:
        model = AccountSettings
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["timezone"].choices = timezone_choices_grouped()
        
        tz = self.initial.get("timezone") or getattr(self.instance, "timezone", "UTC") or "UTC"
        try:
            now_local = datetime.now(ZoneInfo(tz)).strftime("%a %b %d, %Y %I:%M %p")
            self.fields["timezone"].help_text = (
                f"IANA timezone (e.g. America/New_York). Current local time: {now_local}"
            )
        except Exception:
            self.fields["timezone"].help_text = "IANA timezone (e.g. America/New_York)."

    
# ----------------------------
# Inline Models
# ----------------------------

class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    extra = 0
    fk_name = "user"


class TravelPreferencesInline(admin.StackedInline):
    model = TravelPreferences
    can_delete = False
    extra = 0
    fk_name = "user"
    fields = (
        "budget_preference",
        "travel_styles",
        "travel_pace",
        "fitness_level",
        "mobility_restrictions",
    )


class AccountSettingsInline(admin.StackedInline):
    model = AccountSettings
    can_delete = False
    extra = 0
    fk_name = "user"
    form = AccountSettingsAdminForm
    fields = (
        "timezone",
        "language",
        "units",
        "preferred_currency",
        "theme",
        "email_notifications",
        "push_notifications",
    )


# ----------------------------
# Custom User Admin
# ----------------------------

@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    model = User
    inlines = (ProfileInline, TravelPreferencesInline, AccountSettingsInline)

    class Media:
        js = ("accounts/js/timezone_preview.js",)

    ordering = ("email",)
    list_display = (
        "email",
        "first_name",
        "last_name",
        "is_staff",
        "is_verified",
        "is_premium",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_staff",
        "is_superuser",
        "is_active",
        "is_verified",
        "is_premium",
    )

    search_fields = ("email", "first_name", "last_name")
    readonly_fields = ("created_at", "updated_at", "last_login", "date_joined")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {
            "fields": (
                "first_name",
                "last_name",
                "date_of_birth",
                "phone_number",
            )
        }),
        (_("Permissions"), {
            "fields": (
                "is_active",
                "is_staff",
                "is_superuser",
                "groups",
                "user_permissions",
            )
        }),
        (_("Account Status"), {
            "fields": (
                "is_verified",
                "is_premium",
                "premium_expires",
                "profile_visibility",
            )
        }),
        (_("Important dates"), {
            "fields": (
                "last_login",
                "date_joined",
                "created_at",
                "updated_at",
            )
        }),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": (
                "email",
                "first_name",
                "last_name",
                "password1",
                "password2",
                "is_staff",
                "is_superuser",
            ),
        }),
    )


# ----------------------------
# Profile Admin
# ----------------------------

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "home_city",
        "home_country",
        "countries_visited_count",
        "trips_completed_count",
        "created_at",
    )

    search_fields = (
        "user__email",
        "user__first_name",
        "user__last_name",
        "home_city",
        "home_country",
    )

    readonly_fields = ("created_at", "updated_at")


# ----------------------------
# Travel Preferences Admin
# ----------------------------

@admin.register(TravelPreferences)
class TravelPreferencesAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "budget_preference",
        "travel_pace",
        "fitness_level",
    )

    list_filter = (
        "budget_preference",
        "travel_pace",
        "fitness_level",
        "mobility_restrictions",
    )

    search_fields = (
        "user__email",
        "user__first_name",
        "user__last_name",
    )

    readonly_fields = ("created_at", "updated_at")


# ----------------------------
# Account Settings Admin
# ----------------------------

@admin.register(AccountSettings)
class AccountSettingsAdmin(admin.ModelAdmin):
    form = AccountSettingsAdminForm

    class Media:
        js = ("accounts/js/timezone_preview.js",)

    list_display = (
        "user",
        "timezone",
        "language",
        "units",
        "theme",
    )

    list_filter = (
        "language",
        "units",
        "theme",
        "email_notifications",
        "marketing_emails",
    )

    search_fields = (
        "user__email",
        "user__first_name",
        "user__last_name",
    )

    readonly_fields = ("created_at", "updated_at")
