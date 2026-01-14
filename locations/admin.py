# locations/admin.py
from django.contrib import admin
from .models import Country, Region, City, POI


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = [
        'flag_emoji', 'name', 'iso_code', 'continent', 
        'currency_code', 'city_count', 'visitor_count', 'is_featured'
    ]
    list_filter = ['continent', 'is_featured']
    search_fields = ['name', 'iso_code', 'iso3_code']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['is_featured']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'iso_code', 'iso3_code', 'flag_emoji')
        }),
        ('Geographic Data', {
            'fields': ('continent', 'latitude', 'longitude')
        }),
        ('Travel Information', {
            'fields': (
                'currency_code', 'currency_name', 'phone_code',
                'description', 'travel_tips'
            )
        }),
        ('Visa Information', {
            'fields': ('visa_required', 'visa_info'),
            'classes': ('collapse',)
        }),
        ('Featured', {
            'fields': ('is_featured', 'featured_order'),
        }),
        ('Statistics', {
            'fields': ('city_count', 'poi_count', 'visitor_count'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['city_count', 'poi_count', 'visitor_count']


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ['name', 'country', 'code', 'city_count']
    list_filter = ['country']
    search_fields = ['name', 'code', 'country__name']
    prepopulated_fields = {'slug': ('name',)}
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('country', 'name', 'slug', 'code')
        }),
        ('Geographic Data', {
            'fields': ('latitude', 'longitude', 'description')
        }),
        ('Statistics', {
            'fields': ('city_count',),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['city_count']


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'country', 'region', 'population', 
        'poi_count', 'average_rating', 'is_featured'
    ]
    list_filter = ['country', 'is_featured']
    search_fields = ['name', 'country__name']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['is_featured']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('country', 'region', 'name', 'slug')
        }),
        ('Geographic Data', {
            'fields': ('latitude', 'longitude', 'timezone')
        }),
        ('Information', {
            'fields': ('description', 'population', 'best_time_to_visit', 'average_daily_budget')
        }),
        ('Featured', {
            'fields': ('is_featured', 'featured_order'),
        }),
        ('Statistics', {
            'fields': ('poi_count', 'visitor_count', 'average_rating', 'review_count'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['poi_count', 'visitor_count', 'average_rating', 'review_count']


@admin.register(POI)
class POIAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'city', 'poi_type', 'entry_fee', 
        'average_rating', 'review_count', 'is_featured'
    ]
    list_filter = ['poi_type', 'is_featured', 'wheelchair_accessible', 'parking_available']
    search_fields = ['name', 'address', 'city__name']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['is_featured']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('city', 'name', 'slug', 'poi_type')
        }),
        ('Geographic Data', {
            'fields': ('latitude', 'longitude', 'address')
        }),
        ('Information', {
            'fields': ('description', 'website', 'phone')
        }),
        ('Visiting Information', {
            'fields': (
                'entry_fee', 'entry_fee_currency', 
                'opening_hours', 'typical_duration'
            )
        }),
        ('Accessibility', {
            'fields': ('wheelchair_accessible', 'parking_available')
        }),
        ('Featured', {
            'fields': ('is_featured', 'featured_order'),
        }),
        ('Statistics', {
            'fields': ('visitor_count', 'average_rating', 'review_count'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['visitor_count', 'average_rating', 'review_count']