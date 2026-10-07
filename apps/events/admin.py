# events/admin.py
from django.contrib import admin
from .models import EventCategory, Event, EventTag, EventPerformer

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'city', 'start_date', 'status', 'is_featured', 'is_verified']
    list_filter = ['category', 'status', 'is_featured', 'is_verified', 'start_date']
    search_fields = ['name', 'description', 'city__name', 'venue_name']
    date_hierarchy = 'start_date'
    readonly_fields = ['view_count', 'bucket_list_count', 'attendance_count']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'category', 'description', 'short_description')
        }),
        ('Location', {
            'fields': ('city', 'poi', 'venue_name', 'venue_address', 'latitude', 'longitude')
        }),
        ('Timing', {
            'fields': ('start_date', 'end_date', 'start_time', 'end_time', 'timezone', 'is_all_day')
        }),
        ('Ticketing', {
            'fields': ('is_free', 'ticket_price_min', 'ticket_price_max', 'currency', 'ticket_url', 'sold_out')
        }),
        ('Status', {
            'fields': ('status', 'is_verified', 'is_featured')
        }),
    )

