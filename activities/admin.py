# activities/admin.py
from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html
from .models import ActivityCategory, Activity, ActivityTag


@admin.register(ActivityCategory)
class ActivityCategoryAdmin(admin.ModelAdmin):
    list_display = [
        'name', 
        'display_order', 
        'activity_count',
        'icon',
        'is_active',
        'created_at'
    ]
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['display_order', 'name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'description', 'icon')
        }),
        ('Display Settings', {
            'fields': ('display_order', 'is_active')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at']
    
    def activity_count(self, obj):
        return obj.activities.count()
    activity_count.short_description = 'Activities'
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(
            _activity_count=Count('activities', distinct=True)
        )
        return queryset


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'category',
        'skill_level',
        'cost_level',
        'duration_category',
        'popularity_display',
        'rating_display',
        'bucket_list_count',
        'is_featured',
        'created_at'
    ]
    list_filter = [
        'category',
        'skill_level',
        'cost_level',
        'duration_category',
        'best_for',
        'indoor_outdoor',
        'risk_level',
        'is_featured',
        'wheelchair_accessible',
        'suitable_for_children',
        'booking_required',
        'guide_required',
        'created_at'
    ]
    search_fields = ['name', 'description', 'short_description']
    prepopulated_fields = {'slug': ('name',)}
    # REMOVED: filter_horizontal = ['tags']  # This field doesn't exist on Activity
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'category',
                'name',
                'slug',
                'short_description',
                'description'
            )
        }),
        ('Difficulty & Requirements', {
            'fields': (
                'skill_level',
                'fitness_required',
                'age_minimum',
                'age_maximum'
            )
        }),
        ('Time & Cost', {
            'fields': (
                'typical_duration',
                'duration_category',
                'estimated_cost_min',
                'estimated_cost_max',
                'cost_level'
            )
        }),
        ('Activity Characteristics', {
            'fields': (
                'best_for',
                'best_season',
                'indoor_outdoor'
            )
        }),
        ('Requirements & Resources', {
            'fields': (
                'equipment_needed',
                'booking_required',
                'guide_required'
            )
        }),
        ('Accessibility', {
            'fields': (
                'wheelchair_accessible',
                'suitable_for_children'
            )
        }),
        ('Safety', {
            'fields': (
                'risk_level',
                'safety_notes'
            )
        }),
        ('Statistics', {
            'fields': (
                'popularity_score',
                'bucket_list_count',
                'completed_count',
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
    
    readonly_fields = ['created_at', 'updated_at', 'popularity_score', 
                       'bucket_list_count', 'completed_count', 
                       'average_rating', 'review_count']
    
    ordering = ['-popularity_score', 'name']
    
    def popularity_display(self, obj):
        return format_html(
            '<span style="font-weight: bold; color: {};">{}</span>',
            '#28a745' if obj.popularity_score > 100 else '#6c757d',
            obj.popularity_score
        )
    popularity_display.short_description = 'Popularity'
    popularity_display.admin_order_field = 'popularity_score'
    
    def rating_display(self, obj):
        if obj.average_rating:
            stars = '⭐' * int(obj.average_rating)
            return format_html(
                '{} ({:.2f}/5.0 - {} reviews)',
                stars,
                obj.average_rating,
                obj.review_count
            )
        return format_html('<span style="color: #6c757d;">No ratings</span>')
    rating_display.short_description = 'Rating'
    rating_display.admin_order_field = 'average_rating'
    
    actions = ['mark_as_featured', 'unmark_as_featured', 'reset_statistics']
    
    def mark_as_featured(self, request, queryset):
        updated = queryset.update(is_featured=True)
        self.message_user(
            request,
            f'{updated} activity(ies) marked as featured.'
        )
    mark_as_featured.short_description = 'Mark selected as featured'
    
    def unmark_as_featured(self, request, queryset):
        updated = queryset.update(is_featured=False)
        self.message_user(
            request,
            f'{updated} activity(ies) unmarked as featured.'
        )
    unmark_as_featured.short_description = 'Unmark selected as featured'
    
    def reset_statistics(self, request, queryset):
        updated = queryset.update(
            popularity_score=0,
            bucket_list_count=0,
            completed_count=0,
            average_rating=None,
            review_count=0
        )
        self.message_user(
            request,
            f'Statistics reset for {updated} activity(ies).'
        )
    reset_statistics.short_description = 'Reset statistics'


@admin.register(ActivityTag)
class ActivityTagAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'activity_count',
        'usage_count',
        'created_at'
    ]
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ['activities']
    ordering = ['name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'description')
        }),
        ('Activities', {
            'fields': ('activities',)
        }),
        ('Statistics', {
            'fields': ('usage_count',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at', 'usage_count']
    
    def activity_count(self, obj):
        return obj.activities.count()
    activity_count.short_description = 'Activities'
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(
            _activity_count=Count('activities', distinct=True)
        )
        return queryset