# locations/admin.py
from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html
from .models import Country, Region, City, POI


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = [
        'flag_name_display',
        'iso_code',
        'iso3_code',
        'continent',
        'currency_display',
        'city_count',
        'poi_count',
        'visitor_count',
        'is_featured',
        'created_at'
    ]
    list_filter = [
        'continent',
        'is_featured',
        'visa_required',
        'created_at'
    ]
    search_fields = [
        'name',
        'iso_code',
        'iso3_code',
        'description',
        'currency_name'
    ]
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'name',
                'slug',
                'iso_code',
                'iso3_code',
                'flag_emoji',
                'continent'
            )
        }),
        ('Geographic Data', {
            'fields': (
                'latitude',
                'longitude'
            )
        }),
        ('Travel Information', {
            'fields': (
                'currency_code',
                'currency_name',
                'phone_code',
                'description',
                'travel_tips'
            )
        }),
        ('Visa Information', {
            'fields': (
                'visa_required',
                'visa_info'
            ),
            'classes': ('collapse',)
        }),
        ('Statistics', {
            'fields': (
                'city_count',
                'poi_count',
                'visitor_count'
            ),
            'classes': ('collapse',)
        }),
        ('Featured Content', {
            'fields': (
                'is_featured',
                'featured_order',
                'featured_start_date',
                'featured_end_date'
            )
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at', 'city_count', 'poi_count', 'visitor_count']
    
    actions = ['mark_as_featured', 'unmark_as_featured', 'reset_visitor_count']
    
    def flag_name_display(self, obj):
        return format_html(
            '<span style="font-size: 18px;">{}</span> <strong>{}</strong>',
            obj.flag_emoji,
            obj.name
        )
    flag_name_display.short_description = 'Country'
    flag_name_display.admin_order_field = 'name'
    
    def currency_display(self, obj):
        if obj.currency_code and obj.currency_name:
            return f"{obj.currency_code} ({obj.currency_name})"
        return obj.currency_code or '-'
    currency_display.short_description = 'Currency'
    
    def mark_as_featured(self, request, queryset):
        updated = queryset.update(is_featured=True)
        self.message_user(request, f'{updated} country(ies) marked as featured.')
    mark_as_featured.short_description = 'Mark selected as featured'
    
    def unmark_as_featured(self, request, queryset):
        updated = queryset.update(is_featured=False)
        self.message_user(request, f'{updated} country(ies) unmarked as featured.')
    unmark_as_featured.short_description = 'Unmark selected as featured'
    
    def reset_visitor_count(self, request, queryset):
        updated = queryset.update(visitor_count=0)
        self.message_user(request, f'Visitor count reset for {updated} country(ies).')
    reset_visitor_count.short_description = 'Reset visitor count'
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'country',
        'code',
        'city_count',
        'created_at'
    ]
    list_filter = [
        'country',
        'created_at'
    ]
    search_fields = [
        'name',
        'code',
        'description',
        'country__name'
    ]
    autocomplete_fields = ['country']
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['country', 'name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'country',
                'name',
                'slug',
                'code',
                'description'
            )
        }),
        ('Geographic Data', {
            'fields': (
                'latitude',
                'longitude'
            )
        }),
        ('Statistics', {
            'fields': ('city_count',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at', 'city_count']
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('country')
        return queryset


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'country',
        'region',
        'population_display',
        'poi_count',
        'visitor_count',
        'rating_display',
        'is_featured',
        'created_at'
    ]
    list_filter = [
        'country',
        'is_featured',
        'created_at'
    ]
    search_fields = [
        'name',
        'description',
        'country__name',
        'region__name',
        'timezone'
    ]
    autocomplete_fields = ['country', 'region']
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['country', 'name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'country',
                'region',
                'name',
                'slug',
                'description',
                'population'
            )
        }),
        ('Geographic Data', {
            'fields': (
                'latitude',
                'longitude',
                'timezone'
            )
        }),
        ('Travel Information', {
            'fields': (
                'best_time_to_visit',
                'average_daily_budget'
            )
        }),
        ('Statistics', {
            'fields': (
                'poi_count',
                'visitor_count',
                'average_rating',
                'review_count'
            ),
            'classes': ('collapse',)
        }),
        ('Featured Content', {
            'fields': (
                'is_featured',
                'featured_order',
                'featured_start_date',
                'featured_end_date'
            )
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = [
        'created_at',
        'updated_at',
        'poi_count',
        'visitor_count',
        'average_rating',
        'review_count'
    ]
    
    actions = ['mark_as_featured', 'unmark_as_featured', 'reset_statistics']
    
    def population_display(self, obj):
        if obj.population:
            return format_html(
                '<span title="{:,}">{}</span>',
                obj.population,
                self._format_population(obj.population)
            )
        return '-'
    population_display.short_description = 'Population'
    population_display.admin_order_field = 'population'
    
    def _format_population(self, pop):
        """Format population in readable format"""
        if pop >= 1_000_000:
            return f"{pop/1_000_000:.1f}M"
        elif pop >= 1_000:
            return f"{pop/1_000:.0f}K"
        return str(pop)
    
    def rating_display(self, obj):
        if obj.average_rating:
            stars = '⭐' * int(obj.average_rating)
            return format_html(
                '{} ({:.2f}/5.0 - {} reviews)',
                stars,
                obj.average_rating,
                obj.review_count
            )
        return format_html('<span style="color: #9CA3AF;">No ratings</span>')
    rating_display.short_description = 'Rating'
    rating_display.admin_order_field = 'average_rating'
    
    def mark_as_featured(self, request, queryset):
        updated = queryset.update(is_featured=True)
        self.message_user(request, f'{updated} city(ies) marked as featured.')
    mark_as_featured.short_description = 'Mark selected as featured'
    
    def unmark_as_featured(self, request, queryset):
        updated = queryset.update(is_featured=False)
        self.message_user(request, f'{updated} city(ies) unmarked as featured.')
    unmark_as_featured.short_description = 'Unmark selected as featured'
    
    def reset_statistics(self, request, queryset):
        updated = queryset.update(
            poi_count=0,
            visitor_count=0,
            average_rating=None,
            review_count=0
        )
        self.message_user(request, f'Statistics reset for {updated} city(ies).')
    reset_statistics.short_description = 'Reset statistics'
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('country', 'region')
        return queryset


@admin.register(POI)
class POIAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'city',
        'poi_type_display',
        'entry_fee_display',
        'visitor_count',
        'rating_display',
        'wheelchair_accessible',
        'is_featured',
        'created_at'
    ]
    list_filter = [
        'poi_type',
        'is_featured',
        'wheelchair_accessible',
        'parking_available',
        'created_at',
        'city__country'
    ]
    search_fields = [
        'name',
        'description',
        'address',
        'city__name',
        'city__country__name'
    ]
    autocomplete_fields = ['city']
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['city', 'name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'city',
                'name',
                'slug',
                'poi_type',
                'description'
            )
        }),
        ('Location', {
            'fields': (
                'latitude',
                'longitude',
                'address'
            )
        }),
        ('Contact Information', {
            'fields': (
                'website',
                'phone'
            )
        }),
        ('Visiting Information', {
            'fields': (
                'entry_fee',
                'entry_fee_currency',
                'opening_hours',
                'typical_duration'
            )
        }),
        ('Accessibility', {
            'fields': (
                'wheelchair_accessible',
                'parking_available'
            )
        }),
        ('Statistics', {
            'fields': (
                'visitor_count',
                'average_rating',
                'review_count'
            ),
            'classes': ('collapse',)
        }),
        ('Featured Content', {
            'fields': (
                'is_featured',
                'featured_order',
                'featured_start_date',
                'featured_end_date'
            )
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = [
        'created_at',
        'updated_at',
        'visitor_count',
        'average_rating',
        'review_count'
    ]
    
    actions = [
        'mark_as_featured',
        'unmark_as_featured',
        'mark_wheelchair_accessible',
        'reset_statistics'
    ]
    
    def poi_type_display(self, obj):
        colors = {
            'landmark': '#3B82F6',
            'museum': '#8B5CF6',
            'park': '#10B981',
            'beach': '#06B6D4',
            'mountain': '#78716C',
            'temple': '#F59E0B',
            'historical': '#EF4444',
            'viewpoint': '#EC4899',
            'entertainment': '#F97316',
            'shopping': '#A855F7',
            'nightlife': '#6366F1',
            'nature': '#14B8A6',
            'other': '#6B7280'
        }
        color = colors.get(obj.poi_type, '#6B7280')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: 500;">{}</span>',
            color,
            obj.get_poi_type_display()
        )
    poi_type_display.short_description = 'Type'
    poi_type_display.admin_order_field = 'poi_type'
    
    def entry_fee_display(self, obj):
        if obj.entry_fee is not None:
            if obj.entry_fee == 0:
                return format_html(
                    '<span style="color: #10B981; font-weight: 500;">Free</span>'
                )
            currency = obj.entry_fee_currency or 'USD'
            return format_html(
                '<span style="font-weight: 500;">{} {:.2f}</span>',
                currency,
                obj.entry_fee
            )
        return format_html('<span style="color: #9CA3AF;">-</span>')
    entry_fee_display.short_description = 'Entry Fee'
    entry_fee_display.admin_order_field = 'entry_fee'
    
    def rating_display(self, obj):
        if obj.average_rating:
            stars = '⭐' * int(obj.average_rating)
            return format_html(
                '{} ({:.2f}/5.0 - {} reviews)',
                stars,
                obj.average_rating,
                obj.review_count
            )
        return format_html('<span style="color: #9CA3AF;">No ratings</span>')
    rating_display.short_description = 'Rating'
    rating_display.admin_order_field = 'average_rating'
    
    def mark_as_featured(self, request, queryset):
        updated = queryset.update(is_featured=True)
        self.message_user(request, f'{updated} POI(s) marked as featured.')
    mark_as_featured.short_description = 'Mark selected as featured'
    
    def unmark_as_featured(self, request, queryset):
        updated = queryset.update(is_featured=False)
        self.message_user(request, f'{updated} POI(s) unmarked as featured.')
    unmark_as_featured.short_description = 'Unmark selected as featured'
    
    def mark_wheelchair_accessible(self, request, queryset):
        updated = queryset.update(wheelchair_accessible=True)
        self.message_user(request, f'{updated} POI(s) marked as wheelchair accessible.')
    mark_wheelchair_accessible.short_description = 'Mark as wheelchair accessible'
    
    def reset_statistics(self, request, queryset):
        updated = queryset.update(
            visitor_count=0,
            average_rating=None,
            review_count=0
        )
        self.message_user(request, f'Statistics reset for {updated} POI(s).')
    reset_statistics.short_description = 'Reset statistics'
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('city__country', 'city__region')
        return queryset