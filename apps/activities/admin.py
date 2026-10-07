# activities/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from .models import ActivityCategory, Activity, ActivityTag, UserActivityBookmark
from approval_system.models import ApprovalStatus


@admin.register(ActivityCategory)
class ActivityCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'display_order', 'is_active', 'allow_user_submissions', 'activity_count']
    list_filter = ['is_active', 'allow_user_submissions']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['display_order', 'name']
    
    def activity_count(self, obj):
        return obj.activities.count()
    activity_count.short_description = 'Activities'


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'category',
        'created_by',
        'visibility_badge',
        'approval_badge',
        'source',
        'specificity_level',
        'bucket_list_count',
        'event_count',
        'created_at',
    ]
    
    list_filter = [
        'visibility',
        'approval_status',
        'source',
        'category',
        'specificity_level',
        'skill_level',
        'cost_level',
        'best_for',
        'indoor_outdoor',
        'created_at',
    ]
    
    search_fields = [
        'name',
        'description',
        'short_description',
        'created_by__username',
        'created_by__email',
    ]
    
    readonly_fields = [
        'created_at',
        'updated_at',
        'submitted_at',
        'reviewed_at',
        'popularity_score',
        'bucket_list_count',
        'completed_count',
        'event_count',
        'review_count',
        'average_rating',
        'approval_history_link',
    ]
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'name',
                'category',
                'description',
                'short_description',
            )
        }),
        ('Creator & Visibility', {
            'fields': (
                'created_by',
                'visibility',
                'source',
                'specificity_level',
            )
        }),
        ('Approval Status', {
            'fields': (
                'approval_status',
                'approval_priority',
                'submitted_by',
                'submitted_at',
                'reviewed_by',
                'reviewed_at',
                'rejection_notes',
                'approval_history_link',
            ),
            'classes': ('collapse',),
        }),
        ('Suggested Details', {
            'fields': (
                'suggested_location',
                'suggested_timeframe',
                'suggested_date_range_start',
                'suggested_date_range_end',
            ),
            'classes': ('collapse',),
        }),
        ('Activity Details', {
            'fields': (
                'skill_level',
                'fitness_required',
                'age_minimum',
                'age_maximum',
                'typical_duration',
                'duration_category',
            ),
            'classes': ('collapse',),
        }),
        ('Cost Information', {
            'fields': (
                'cost_level',
                'estimated_cost_min',
                'estimated_cost_max',
            ),
            'classes': ('collapse',),
        }),
        ('Characteristics', {
            'fields': (
                'best_for',
                'best_season',
                'indoor_outdoor',
                'equipment_needed',
                'booking_required',
                'guide_required',
            ),
            'classes': ('collapse',),
        }),
        ('Accessibility & Safety', {
            'fields': (
                'wheelchair_accessible',
                'suitable_for_children',
                'risk_level',
                'safety_notes',
            ),
            'classes': ('collapse',),
        }),
        ('Stats', {
            'fields': (
                'popularity_score',
                'bucket_list_count',
                'completed_count',
                'event_count',
                'average_rating',
                'review_count',
            ),
            'classes': ('collapse',),
        }),
        ('Metadata', {
            'fields': (
                'slug',
                'is_featured',
                'featured_order',
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )
    
    actions = [
        'approve_selected',
        'reject_selected',
        'mark_as_pending',
        'make_public',
        'make_private',
    ]
    
    def visibility_badge(self, obj):
        colors = {
            'private': 'gray',
            'public': 'green',
        }
        color = colors.get(obj.visibility, 'blue')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color,
            obj.get_visibility_display()
        )
    visibility_badge.short_description = 'Visibility'
    
    def approval_badge(self, obj):
        colors = {
            ApprovalStatus.DRAFT: 'gray',
            ApprovalStatus.PENDING: 'orange',
            ApprovalStatus.APPROVED: 'green',
            ApprovalStatus.REJECTED: 'red',
            ApprovalStatus.CHANGES_REQUESTED: 'purple',
            ApprovalStatus.ARCHIVED: 'darkgray',
        }
        color = colors.get(obj.approval_status, 'blue')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color,
            obj.get_approval_status_display()
        )
    approval_badge.short_description = 'Approval'
    
    def approval_history_link(self, obj):
        if obj.pk:
            url = reverse('admin:approval_system_approvallog_changelist')
            # Filter by this activity
            return format_html(
                '<a href="{}?content_type__model=activity&object_id={}" target="_blank">View History</a>',
                url,
                obj.pk
            )
        return '-'
    approval_history_link.short_description = 'Approval History'
    
    def approve_selected(self, request, queryset):
        count = 0
        for activity in queryset:
            if activity.approval_status != ApprovalStatus.APPROVED:
                activity.approve(request.user, notes='Bulk approved from admin')
                count += 1
        self.message_user(request, f'{count} activities approved.')
    approve_selected.short_description = 'Approve selected activities'
    
    def reject_selected(self, request, queryset):
        count = 0
        for activity in queryset:
            if activity.approval_status not in [ApprovalStatus.REJECTED, ApprovalStatus.APPROVED]:
                activity.reject(request.user, notes='Bulk rejected from admin')
                count += 1
        self.message_user(request, f'{count} activities rejected.')
    reject_selected.short_description = 'Reject selected activities'
    
    def mark_as_pending(self, request, queryset):
        count = queryset.update(
            approval_status=ApprovalStatus.PENDING,
            submitted_at=timezone.now()
        )
        self.message_user(request, f'{count} activities marked as pending.')
    mark_as_pending.short_description = 'Mark as pending review'
    
    def make_public(self, request, queryset):
        count = queryset.update(visibility='public')
        self.message_user(request, f'{count} activities changed to public.')
    make_public.short_description = 'Change to public visibility'
    
    def make_private(self, request, queryset):
        count = queryset.update(visibility='private')
        self.message_user(request, f'{count} activities changed to private.')
    make_private.short_description = 'Change to private visibility'
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Staff can see everything
        return qs.select_related('category', 'created_by', 'submitted_by', 'reviewed_by')


@admin.register(ActivityTag)
class ActivityTagAdmin(admin.ModelAdmin):
    list_display = ['name', 'usage_count', 'user_can_add', 'created_at']
    list_filter = ['user_can_add', 'created_at']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ['activities']
    
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Update usage count
        obj.usage_count = obj.activities.count()
        obj.save()


@admin.register(UserActivityBookmark)
class UserActivityBookmarkAdmin(admin.ModelAdmin):
    list_display = ['user', 'activity', 'interest_level', 'created_at']
    list_filter = ['interest_level', 'created_at']
    search_fields = ['user__username', 'activity__name', 'notes']
    raw_id_fields = ['user', 'activity']
    readonly_fields = ['created_at', 'updated_at']
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('user', 'activity')
