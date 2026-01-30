# locations/admin.py
from django.contrib import admin
from approval_system.admin import ApprovableAdminMixin
from .models import Country, Region, City, POI


@admin.register(Country)
class CountryAdmin(ApprovableAdminMixin, admin.ModelAdmin):
    list_display = [
        'flag_emoji', 'name', 'iso_code', 'continent', 
        'currency_code', 'get_city_count', 'visitor_count', 'is_featured'
    ]
    # ApprovableAdminMixin automatically adds: approval_status_badge, submitted_by, reviewed_by
    
    list_filter = ['continent', 'is_featured']
    # ApprovableAdminMixin automatically adds: approval_status, approval_priority, submitted_at
    
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
            'fields': ('get_city_count_display', 'get_poi_count_display', 'visitor_count'),
            'classes': ('collapse',)
        }),
        ('Approval Information', {
            'fields': ('approval_status', 'approval_priority', 
                      'submitted_by', 'submitted_at',
                      'reviewed_by', 'reviewed_at'),
            'classes': ('collapse',)
        }),        
       ('Featured Media', {
            'fields': ('featured_media',), 
            'classes': ('collapse',)
        }),          
    )
    
    # ApprovableAdminMixin automatically adds these to readonly_fields,
    # but we include our custom ones here
    readonly_fields = [
        'get_city_count_display', 'get_poi_count_display', 'visitor_count',
        'submitted_by', 'submitted_at', 'reviewed_by', 'reviewed_at'
    ]
    
    def get_queryset(self, request):
        """Optimize queryset with count annotations"""
        from django.db.models import Count, Q
        from approval_system.models import ApprovalStatus
        
        qs = super().get_queryset(request)
        return qs.annotate(
            _city_count=Count('cities', filter=Q(cities__approval_status=ApprovalStatus.APPROVED)),
            _poi_count=Count('cities__pois', filter=Q(cities__pois__approval_status=ApprovalStatus.APPROVED))
        )
    
    def get_city_count(self, obj):
        """Display city count in list view"""
        return getattr(obj, '_city_count', obj.city_count)
    get_city_count.short_description = 'Cities'
    get_city_count.admin_order_field = '_city_count'
    
    def get_poi_count(self, obj):
        """Display POI count in list view"""
        return getattr(obj, '_poi_count', obj.poi_count)
    get_poi_count.short_description = 'POIs'
    get_poi_count.admin_order_field = '_poi_count'
    
    def get_city_count_display(self, obj):
        """Display city count in detail view"""
        return obj.city_count
    get_city_count_display.short_description = 'Number of Cities'
    
    def get_poi_count_display(self, obj):
        """Display POI count in detail view"""
        return obj.poi_count
    get_poi_count_display.short_description = 'Number of POIs'


@admin.register(Region)
class RegionAdmin(ApprovableAdminMixin, admin.ModelAdmin):
    list_display = ['name', 'country', 'code', 'get_city_count']
    # ApprovableAdminMixin automatically adds: approval_status_badge, submitted_by, reviewed_by
    
    list_filter = ['country']
    # ApprovableAdminMixin automatically adds: approval_status, approval_priority, submitted_at
    
    search_fields = ['name', 'code', 'country__name']
    prepopulated_fields = {'slug': ('name',)}
    autocomplete_fields = ['country']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('country', 'name', 'slug', 'code')
        }),
        ('Geographic Data', {
            'fields': ('latitude', 'longitude', 'description')
        }),
        ('Statistics', {
            'fields': ('get_city_count_display',),
            'classes': ('collapse',)
        }),
        ('Approval Information', {
            'fields': ('approval_status', 'approval_priority',
                      'submitted_by', 'submitted_at',
                      'reviewed_by', 'reviewed_at'),
            'classes': ('collapse',)
        }),
       ('Featured Media', {
            'fields': ('featured_media',), 
            'classes': ('collapse',)
        }),          
    )
    
    readonly_fields = [
        'get_city_count_display',
        'submitted_by', 'submitted_at', 'reviewed_by', 'reviewed_at'
    ]
    
    def get_queryset(self, request):
        """Optimize queryset with city count annotation"""
        from django.db.models import Count, Q
        from approval_system.models import ApprovalStatus
        
        qs = super().get_queryset(request)
        return qs.annotate(
            _city_count=Count('cities', filter=Q(cities__approval_status=ApprovalStatus.APPROVED))
        )
    
    def get_city_count(self, obj):
        """Display city count in list view"""
        # Use annotated value if available, otherwise fall back to property
        return getattr(obj, '_city_count', obj.city_count)
    get_city_count.short_description = 'Cities'
    get_city_count.admin_order_field = '_city_count'  # Allows column order sorting
    
    def get_city_count_display(self, obj):
        """Display city count in detail view"""
        return obj.city_count
    get_city_count_display.short_description = 'Number of Cities'


@admin.register(City)
class CityAdmin(ApprovableAdminMixin, admin.ModelAdmin):
    list_display = [
        'name', 'country', 'region', 'population', 
        'get_poi_count', 'average_rating', 'is_featured'
    ]
    # ApprovableAdminMixin automatically adds: approval_status_badge, submitted_by, reviewed_by
    
    list_filter = ['country', 'is_featured']
    # ApprovableAdminMixin automatically adds: approval_status, approval_priority, submitted_at
    
    search_fields = ['name', 'country__name', 'region__name']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['is_featured']
    autocomplete_fields = ['country', 'region']
    
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
            'fields': ('get_poi_count_display', 'visitor_count', 'average_rating', 'review_count'),
            'classes': ('collapse',)
        }),
        ('Approval Information', {
            'fields': ('approval_status', 'approval_priority',
                      'submitted_by', 'submitted_at',
                      'reviewed_by', 'reviewed_at'),
            'classes': ('collapse',)
        }),
       ('Featured Media', {
            'fields': ('featured_media',), 
            'classes': ('collapse',)
        }),          
    )
    
    readonly_fields = [
        'get_poi_count_display', 'visitor_count', 'average_rating', 'review_count',
        'submitted_by', 'submitted_at', 'reviewed_by', 'reviewed_at'
    ]
    
    def get_queryset(self, request):
        """Optimize queryset with POI count annotation"""
        from django.db.models import Count, Q
        from approval_system.models import ApprovalStatus
        
        qs = super().get_queryset(request)
        return qs.annotate(
            _poi_count=Count('pois', filter=Q(pois__approval_status=ApprovalStatus.APPROVED))
        )
    
    def get_poi_count(self, obj):
        """Display POI count in list view"""
        return getattr(obj, '_poi_count', obj.poi_count)
    get_poi_count.short_description = 'POIs'
    get_poi_count.admin_order_field = '_poi_count'
    
    def get_poi_count_display(self, obj):
        """Display POI count in detail view"""
        return obj.poi_count
    get_poi_count_display.short_description = 'Number of POIs'



@admin.register(POI)
class POIAdmin(ApprovableAdminMixin, admin.ModelAdmin):
    list_display = [
        'name', 'city', 'poi_type', 'entry_fee', 
        'average_rating', 'review_count', 'is_featured'
    ]
    # ApprovableAdminMixin automatically adds: approval_status_badge, submitted_by, reviewed_by
    
    list_filter = ['poi_type', 'is_featured', 'wheelchair_accessible', 'parking_available']
    # ApprovableAdminMixin automatically adds: approval_status, approval_priority, submitted_at
    
    search_fields = ['name', 'address', 'city__name']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['is_featured']
    autocomplete_fields = ['city']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('city', 'name', 'slug', 'poi_type')
        }),
        ('Geographic Data', {
            'fields': ('latitude', 'longitude', 'address', 'elevation_m')
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
        ('Approval Information', {
            'fields': ('approval_status', 'approval_priority',
                      'submitted_by', 'submitted_at',
                      'reviewed_by', 'reviewed_at'),
            'classes': ('collapse',)
        }),
       ('Featured Media', {
            'fields': ('featured_media',), 
            'classes': ('collapse',)
        }),          
    )
    
    readonly_fields = [
        'visitor_count', 'average_rating', 'review_count',
        'submitted_by', 'submitted_at', 'reviewed_by', 'reviewed_at'
    ]
