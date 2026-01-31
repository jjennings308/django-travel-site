# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.translation import gettext_lazy as _
from django import forms
from datetime import datetime
from zoneinfo import available_timezones, ZoneInfo

from .models import (
    User, Profile, TravelPreferences, AccountSettings,
    RoleRequest, VendorProfile, ContentProviderProfile
)

# UPDATED: Import AccountSettingsForm which now has dynamic currency choices
from .forms import AccountSettingsForm

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


# UPDATED: Changed to inherit from AccountSettingsForm to get dynamic currency choices
class AccountSettingsAdminForm(AccountSettingsForm):
    """
    Admin form for AccountSettings that includes:
    - Dynamic currency choices from AccountSettingsForm
    - Timezone dropdown with preview
    """
    timezone = forms.ChoiceField(choices=[], required=True)

    class Meta:
        model = AccountSettings
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Currency choices are already set by AccountSettingsForm.__init__()
        
        # Set up timezone choices
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

    ordering = ("username",)
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "subscription_tier",
        "is_verified",
        "is_vendor",
        "is_content_provider",
        "is_staff",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_staff",
        "is_superuser",
        "is_active",
        "is_verified",
        "subscription_tier",
        "groups",
    )

    search_fields = ("username", "email", "first_name", "last_name")
    readonly_fields = ("created_at", "updated_at", "last_login", "date_joined")

    fieldsets = (
        (None, {"fields": ("username", "email", "password")}),
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
                "subscription_tier",
                "subscription_expires",
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
                "username",
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
    
    def is_vendor(self, obj):
        """Show if user has vendor role"""
        return obj.is_vendor
    is_vendor.boolean = True
    is_vendor.short_description = "Vendor"
    
    def is_content_provider(self, obj):
        """Show if user has content provider role"""
        return obj.is_content_provider
    is_content_provider.boolean = True
    is_content_provider.short_description = "Content Provider"


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
        "user__username",
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
        "user__username",
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
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
    )

    readonly_fields = ("created_at", "updated_at")


# ----------------------------
# Role Request Admin
# ----------------------------

@admin.register(RoleRequest)
class RoleRequestAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "requested_role",
        "status",
        "created_at",
        "reviewed_at",
        "reviewed_by",
    )
    
    list_filter = (
        "status",
        "requested_role",
        "created_at",
    )
    
    search_fields = (
        "user__username",
        "user__email",
        "business_name",
    )
    
    readonly_fields = (
        "created_at",
        "updated_at",
        "reviewed_at",
    )
    
    fieldsets = (
        ("Request Information", {
            "fields": (
                "user",
                "requested_role",
                "status",
                "created_at",
            )
        }),
        ("Application Details", {
            "fields": (
                "business_name",
                "business_description",
                "website",
                "business_license",
                "supporting_documents",
            )
        }),
        ("Review", {
            "fields": (
                "reviewed_by",
                "reviewed_at",
                "review_notes",
                "rejection_reason",
            )
        }),
    )
    
    def save_model(self, request, obj, form, change):
        """Auto-handle status changes from admin"""
        if change:  # If editing existing
            old_status = RoleRequest.objects.get(pk=obj.pk).status
            new_status = obj.status
            
            # If manually approved in admin
            if old_status == 'pending' and new_status == 'approved':
                obj.approve(reviewed_by=request.user)
                return  # approve() calls save()
            
            # If manually rejected in admin
            elif old_status == 'pending' and new_status == 'rejected':
                if not obj.rejection_reason:
                    obj.rejection_reason = "Manually rejected by admin"
                obj.reject(reviewed_by=request.user, reason=obj.rejection_reason)
                return  # reject() calls save()
        
        super().save_model(request, obj, form, change)


# ----------------------------
# Vendor Profile Admin
# ----------------------------

@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "business_name",
        "verification_status",
        "total_listings",
        "average_rating",
        "total_bookings",
    )
    
    list_filter = (
        "verification_status",
    )
    
    search_fields = (
        "user__username",
        "user__email",
        "business_name",
    )
    
    readonly_fields = ("created_at", "updated_at")


# ----------------------------
# Content Provider Profile Admin
# ----------------------------

@admin.register(ContentProviderProfile)
class ContentProviderProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "total_contributions",
        "content_rating",
    )
    
    search_fields = (
        "user__username",
        "user__email",
    )
    
    readonly_fields = ("created_at", "updated_at")
