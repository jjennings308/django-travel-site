# bucketlists/admin.py
from django.contrib import admin
from django.db.models import Count, Q
from django.utils.html import format_html
from django.utils import timezone
from .models import (
    BucketListItem, 
    BucketListCategory, 
    BucketListItemCategory,
    BucketListMilestone
)


class BucketListItemCategoryInline(admin.TabularInline):
    model = BucketListItemCategory
    extra = 1
    autocomplete_fields = ['category']


@admin.register(BucketListItem)
class BucketListItemAdmin(admin.ModelAdmin):
    list_display = [
        'title_display',
        'user',
        'content_type_display',
        'status_display',
        'priority_display',
        'target_date',
        'completed_date',
        'rating_display',
        'is_public',
        'created_at'
    ]
    list_filter = [
        'status',
        'priority',
        'is_public',
        'target_season',
        'reminder_enabled',
        'created_at',
        'completed_date'
    ]
    search_fields = [
        'custom_title',
        'custom_description',
        'personal_notes',
        'user__username',
        'user__email',
        'activity__name',
        'city__name',
        'event__name'
    ]
    autocomplete_fields = ['user', 'activity', 'event']  # REMOVED 'city'
    raw_id_fields = ['city']  # ADDED: Use raw_id instead
    inlines = [BucketListItemCategoryInline]
    
    fieldsets = (
        ('User', {
            'fields': ('user',)
        }),
        ('Content Reference', {
            'fields': (
                'activity',
                'city',
                'event',
                'custom_title',
                'custom_description'
            ),
            'description': 'Select ONE: activity, city, event, OR enter custom title'
        }),
        ('Personal Details', {
            'fields': (
                'personal_notes',
                'with_who',
                'inspiration_source',
                'tags'
            )
        }),
        ('Planning', {
            'fields': (
                'target_date',
                'target_season',
                'estimated_budget',
                'budget_currency'
            )
        }),
        ('Status & Priority', {
            'fields': (
                'status',
                'priority',
                'display_order'
            )
        }),
        ('Completion', {
            'fields': (
                'completed_date',
                'completion_notes',
                'user_rating'
            ),
            'classes': ('collapse',)
        }),
        ('Reminders', {
            'fields': (
                'reminder_enabled',
                'next_reminder_date'
            ),
            'classes': ('collapse',)
        }),
        ('Visibility', {
            'fields': ('is_public',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at']
    
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    
    actions = [
        'mark_as_completed',
        'mark_as_planning',
        'make_public',
        'make_private',
        'set_high_priority',
        'enable_reminders'
    ]
    
    def title_display(self, obj):
        return obj.title
    title_display.short_description = 'Title'
    
    def content_type_display(self, obj):
        if obj.activity:
            return format_html(
                '<span style="background: #3B82F6; color: white; padding: 2px 6px; border-radius: 3px;">Activity</span>'
            )
        elif obj.city:
            return format_html(
                '<span style="background: #10B981; color: white; padding: 2px 6px; border-radius: 3px;">City</span>'
            )
        elif obj.event:
            return format_html(
                '<span style="background: #F59E0B; color: white; padding: 2px 6px; border-radius: 3px;">Event</span>'
            )
        elif obj.custom_title:
            return format_html(
                '<span style="background: #6B7280; color: white; padding: 2px 6px; border-radius: 3px;">Custom</span>'
            )
        return format_html('<span style="color: #EF4444;">None</span>')
    content_type_display.short_description = 'Type'
    
    def status_display(self, obj):
        colors = {
            'wishlist': '#6B7280',
            'researching': '#3B82F6',
            'planning': '#8B5CF6',
            'booked': '#F59E0B',
            'in_progress': '#10B981',
            'completed': '#059669',
            'abandoned': '#EF4444'
        }
        color = colors.get(obj.status, '#6B7280')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 3px; font-weight: 500;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_display.short_description = 'Status'
    status_display.admin_order_field = 'status'
    
    def priority_display(self, obj):
        colors = {
            1: '#94A3B8',
            2: '#64748B',
            3: '#F59E0B',
            4: '#EF4444',
            5: '#DC2626'
        }
        stars = '★' * obj.priority
        color = colors.get(obj.priority, '#94A3B8')
        return format_html(
            '<span style="color: {}; font-size: 16px;">{}</span>',
            color,
            stars
        )
    priority_display.short_description = 'Priority'
    priority_display.admin_order_field = 'priority'
    
    def rating_display(self, obj):
        if obj.user_rating:
            stars = '⭐' * obj.user_rating
            return format_html('<span title="{}/5">{}</span>', obj.user_rating, stars)
        return format_html('<span style="color: #9CA3AF;">Not rated</span>')
    rating_display.short_description = 'Rating'
    rating_display.admin_order_field = 'user_rating'
    
    def mark_as_completed(self, request, queryset):
        updated = queryset.update(
            status='completed',
            completed_date=timezone.now().date()
        )
        self.message_user(request, f'{updated} item(s) marked as completed.')
    mark_as_completed.short_description = 'Mark as completed'
    
    def mark_as_planning(self, request, queryset):
        updated = queryset.update(status='planning')
        self.message_user(request, f'{updated} item(s) marked as planning.')
    mark_as_planning.short_description = 'Mark as planning'
    
    def make_public(self, request, queryset):
        updated = queryset.update(is_public=True)
        self.message_user(request, f'{updated} item(s) made public.')
    make_public.short_description = 'Make public'
    
    def make_private(self, request, queryset):
        updated = queryset.update(is_public=False)
        self.message_user(request, f'{updated} item(s) made private.')
    make_private.short_description = 'Make private'
    
    def set_high_priority(self, request, queryset):
        updated = queryset.update(priority=5)
        self.message_user(request, f'{updated} item(s) set to high priority.')
    set_high_priority.short_description = 'Set high priority'
    
    def enable_reminders(self, request, queryset):
        updated = queryset.update(reminder_enabled=True)
        self.message_user(request, f'Reminders enabled for {updated} item(s).')
    enable_reminders.short_description = 'Enable reminders'
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('user', 'activity', 'city', 'event')
        return queryset


@admin.register(BucketListCategory)
class BucketListCategoryAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'user',
        'color_display',
        'icon',
        'item_count_display',
        'display_order',
        'created_at'
    ]
    list_filter = ['created_at']
    search_fields = ['name', 'description', 'user__username', 'user__email']
    autocomplete_fields = ['user']
    ordering = ['user', 'display_order', 'name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'name', 'description')
        }),
        ('Appearance', {
            'fields': ('color', 'icon', 'display_order')
        }),
        ('Statistics', {
            'fields': ('item_count',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at', 'item_count']
    
    def color_display(self, obj):
        return format_html(
            '<div style="width: 30px; height: 20px; background-color: {}; border: 1px solid #ccc; border-radius: 3px;"></div>',
            obj.color
        )
    color_display.short_description = 'Color'
    
    def item_count_display(self, obj):
        count = obj.item_memberships.count()
        return format_html(
            '<span style="font-weight: bold;">{}</span> items',
            count
        )
    item_count_display.short_description = 'Items'
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('user')
        queryset = queryset.annotate(
            _item_count=Count('item_memberships', distinct=True)
        )
        return queryset


@admin.register(BucketListItemCategory)
class BucketListItemCategoryAdmin(admin.ModelAdmin):
    list_display = [
        'item_title',
        'category_name',
        'user',
        'added_at'
    ]
    list_filter = ['added_at']
    search_fields = [
        'item__custom_title',
        'category__name',
        'item__user__username'
    ]
    autocomplete_fields = ['item', 'category']
    date_hierarchy = 'added_at'
    ordering = ['-added_at']
    
    def item_title(self, obj):
        return obj.item.title
    item_title.short_description = 'Item'
    
    def category_name(self, obj):
        return obj.category.name
    category_name.short_description = 'Category'
    
    def user(self, obj):
        return obj.item.user.username
    user.short_description = 'User'
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related(
            'item__user',
            'category__user',
            'item__activity',
            'item__city',
            'item__event'
        )
        return queryset


@admin.register(BucketListMilestone)
class BucketListMilestoneAdmin(admin.ModelAdmin):
    list_display = [
        'title',
        'user',
        'milestone_type',
        'progress_display',
        'achievement_display',
        'achieved_date',
        'created_at'
    ]
    list_filter = [
        'milestone_type',
        'is_achieved',
        'created_at',
        'achieved_date'
    ]
    search_fields = [
        'title',
        'description',
        'user__username',
        'user__email'
    ]
    autocomplete_fields = ['user']
    ordering = ['user', '-is_achieved', 'milestone_type']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'milestone_type', 'title', 'description')
        }),
        ('Progress', {
            'fields': ('target_count', 'current_count')
        }),
        ('Achievement', {
            'fields': ('is_achieved', 'achieved_date')
        }),
        ('Badge', {
            'fields': ('badge_icon', 'badge_color'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at']
    
    actions = ['check_achievements', 'reset_progress']
    
    def progress_display(self, obj):
        percentage = obj.progress_percentage
        color = '#10B981' if percentage >= 100 else '#3B82F6' if percentage >= 50 else '#F59E0B'
        return format_html(
            '<div style="display: flex; align-items: center; gap: 8px;">'
            '<div style="flex: 1; background: #E5E7EB; border-radius: 10px; height: 20px; overflow: hidden;">'
            '<div style="background: {}; height: 100%; width: {}%; transition: width 0.3s;"></div>'
            '</div>'
            '<span style="font-weight: 500; min-width: 80px;">{}/{} ({}%)</span>'
            '</div>',
            color,
            percentage,
            obj.current_count,
            obj.target_count,
            int(percentage)
        )
    progress_display.short_description = 'Progress'
    
    def achievement_display(self, obj):
        if obj.is_achieved:
            return format_html(
                '<span style="background: #10B981; color: white; padding: 4px 8px; border-radius: 3px; font-weight: 500;">✓ Achieved</span>'
            )
        return format_html(
            '<span style="background: #6B7280; color: white; padding: 4px 8px; border-radius: 3px;">In Progress</span>'
        )
    achievement_display.short_description = 'Status'
    achievement_display.admin_order_field = 'is_achieved'
    
    def check_achievements(self, request, queryset):
        achieved_count = 0
        for milestone in queryset:
            if milestone.check_achievement():
                achieved_count += 1
        self.message_user(
            request,
            f'Checked {queryset.count()} milestone(s). {achieved_count} newly achieved!'
        )
    check_achievements.short_description = 'Check for achievements'
    
    def reset_progress(self, request, queryset):
        updated = queryset.update(
            current_count=0,
            is_achieved=False,
            achieved_date=None
        )
        self.message_user(request, f'Progress reset for {updated} milestone(s).')
    reset_progress.short_description = 'Reset progress'
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('user')
        return queryset