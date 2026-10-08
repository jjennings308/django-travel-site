# events/admin.py
from django.contrib import admin

from apps.approval_system.admin import ApprovableAdminMixin

from .models import Event, EventCategory, EventPerformer, EventTag


class EventPerformerInline(admin.TabularInline):
    model = EventPerformer
    extra = 1
    fields = ["name", "performer_type", "is_headliner", "performance_time", "display_order"]


@admin.register(Event)
class EventAdmin(ApprovableAdminMixin, admin.ModelAdmin):
    list_display = ['name', 'category', 'city', 'start_date', 'status', 'created_by', 'is_featured']
    list_filter = ['category', 'status', 'is_featured', 'is_verified', 'start_date']
    search_fields = ['name', 'description', 'city__name', 'venue_name', 'created_by__username']
    date_hierarchy = 'start_date'
    autocomplete_fields = ['city']
    readonly_fields = ['created_by', 'view_count', 'bucket_list_count', 'attendance_count']
    inlines = [EventPerformerInline]

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'category', 'event_type', 'description', 'short_description', 'organizer')
        }),
        ('Location', {
            'fields': ('city', 'poi', 'venue_name', 'venue_address', 'latitude', 'longitude')
        }),
        ('Timing', {
            'fields': ('start_date', 'end_date', 'start_time', 'end_time', 'timezone', 'is_all_day')
        }),
        ('Ticketing', {
            'fields': ('is_free', 'ticket_price_min', 'ticket_price_max', 'currency', 'ticket_url', 'sold_out', 'website')
        }),
        ('Status', {
            'fields': ('status', 'cancellation_reason', 'is_verified', 'is_featured')
        }),
        ('Approval', {
            'fields': ('approval_status', 'approval_priority', 'created_by', 'submitted_by', 'submitted_at', 'reviewed_by', 'reviewed_at')
        }),
    )


@admin.register(EventCategory)
class EventCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'icon', 'display_order']
    list_editable = ['display_order']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(EventTag)
class EventTagAdmin(admin.ModelAdmin):
    list_display = ['name', 'usage_count']
    search_fields = ['name']
