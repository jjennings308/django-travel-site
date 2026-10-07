# vendors/admin.py
from django.contrib import admin
from .models import VendorCategory, VendorType, Vendor, VendorAmenity

@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ['name', 'vendor_type', 'city', 'price_range', 'average_rating', 'is_verified', 'is_active']
    list_filter = ['vendor_type', 'price_range', 'is_verified', 'is_active', 'is_partner']
    search_fields = ['name', 'description', 'city__name']
    readonly_fields = ['review_count', 'average_rating', 'booking_count', 'view_count']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'vendor_type', 'description', 'short_description')
        }),
        ('Location', {
            'fields': ('city', 'poi', 'address', 'latitude', 'longitude')
        }),
        ('Contact', {
            'fields': ('phone', 'email', 'website', 'booking_url')
        }),
        ('Pricing', {
            'fields': ('price_range', 'average_price', 'currency')
        }),
        ('Status', {
            'fields': ('is_active', 'is_verified', 'verified_date', 'is_partner', 'claimed_by_owner')
        }),
        ('Stats', {
            'fields': ('review_count', 'average_rating', 'booking_count', 'view_count'),
            'classes': ('collapse',)
        }),
    )
