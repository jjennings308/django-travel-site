# reviews/admin.py
from django.contrib import admin
from django.db.models import Count, Avg
from django.utils.html import format_html
from django.utils import timezone
from .models import Review, ReviewResponse, ReviewHelpful, ReviewReport


class ReviewResponseInline(admin.StackedInline):
    model = ReviewResponse
    extra = 0
    max_num = 1
    fields = ['responder', 'responder_type', 'response_text', 'is_approved']
    autocomplete_fields = ['responder']


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = [
        'review_target_display',
        'user',
        'rating_display',
        'review_type',
        'visit_date',
        'helpful_display',
        'is_verified_visit',
        'approval_status_display',
        'has_response',
        'created_at'
    ]
    list_filter = [
        'review_type',
        'rating',
        'is_approved',
        'is_featured',
        'is_flagged',
        'is_verified_visit',
        'has_response',
        'travel_type',
        'site_feedback_category',
        'created_at',
        'visit_date'
    ]
    search_fields = [
        'title',
        'comment',
        'user__username',
        'user__email',
        'vendor__name',
        'activity__name',
        'event__name',
        'location__name',
        'trip__title'
    ]
    autocomplete_fields = ['user', 'vendor', 'activity', 'event', 'location', 'trip']
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    inlines = [ReviewResponseInline]
    
    fieldsets = (
        ('Reviewer', {
            'fields': ('user',)
        }),
        ('Review Target', {
            'fields': (
                'review_type',
                'vendor',
                'activity',
                'event',
                'location',
                'trip'
            ),
            'description': 'Select ONE target based on review_type (or none for site feedback)'
        }),
        ('Rating', {
            'fields': (
                'rating',
                'value_rating',
                'service_rating',
                'cleanliness_rating',
                'difficulty_rating'
            )
        }),
        ('Review Content', {
            'fields': (
                'title',
                'comment',
                'pros',
                'cons',
                'tips'
            )
        }),
        ('Context', {
            'fields': (
                'visit_date',
                'travel_type',
                'is_verified_visit'
            )
        }),
        ('Site Feedback', {
            'fields': ('site_feedback_category',),
            'classes': ('collapse',)
        }),
        ('Moderation', {
            'fields': (
                'is_approved',
                'is_featured',
                'is_flagged',
                'flagged_reason'
            )
        }),
        ('Engagement', {
            'fields': (
                'helpful_count',
                'report_count',
                'has_response'
            ),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = [
        'created_at',
        'updated_at',
        'helpful_count',
        'report_count',
        'has_response'
    ]
    
    actions = [
        'approve_reviews',
        'disapprove_reviews',
        'mark_as_featured',
        'unmark_as_featured',
        'mark_as_verified',
        'flag_reviews',
        'unflag_reviews'
    ]
    
    def review_target_display(self, obj):
        target = obj.get_review_target_name()
        colors = {
            'vendor': '#3B82F6',
            'activity': '#10B981',
            'event': '#F59E0B',
            'location': '#8B5CF6',
            'trip': '#EC4899',
            'site': '#6B7280'
        }
        color = colors.get(obj.review_type, '#6B7280')
        return format_html(
            '<div><span style="background: {}; color: white; padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: 500;">{}</span></div>'
            '<div style="margin-top: 4px; font-weight: 500;">{}</div>',
            color,
            obj.get_review_type_display(),
            target
        )
    review_target_display.short_description = 'Review Target'
    
    def rating_display(self, obj):
        stars = '⭐' * obj.rating
        color = '#059669' if obj.rating >= 4 else '#F59E0B' if obj.rating >= 3 else '#EF4444'
        
        # Show detailed ratings if available
        details = []
        if obj.value_rating:
            details.append(f'Value: {obj.value_rating}★')
        if obj.service_rating:
            details.append(f'Service: {obj.service_rating}★')
        if obj.cleanliness_rating:
            details.append(f'Clean: {obj.cleanliness_rating}★')
        if obj.difficulty_rating:
            details.append(f'Difficulty: {obj.difficulty_rating}★')
        
        detail_html = '<br><small style="color: #6B7280;">' + ' | '.join(details) + '</small>' if details else ''
        
        return format_html(
            '<div style="color: {}; font-size: 16px;" title="{}/5">{}</div>{}',
            color,
            obj.rating,
            stars,
            detail_html
        )
    rating_display.short_description = 'Rating'
    rating_display.admin_order_field = 'rating'
    
    def helpful_display(self, obj):
        if obj.helpful_count > 0:
            return format_html(
                '<span style="color: #10B981; font-weight: 500;">👍 {}</span>',
                obj.helpful_count
            )
        return format_html('<span style="color: #9CA3AF;">0</span>')
    helpful_display.short_description = 'Helpful'
    helpful_display.admin_order_field = 'helpful_count'
    
    def approval_status_display(self, obj):
        if obj.is_flagged:
            return format_html(
                '<span style="background: #EF4444; color: white; padding: 3px 8px; border-radius: 3px; font-weight: 500;">🚩 Flagged</span>'
            )
        elif not obj.is_approved:
            return format_html(
                '<span style="background: #F59E0B; color: white; padding: 3px 8px; border-radius: 3px; font-weight: 500;">⏳ Pending</span>'
            )
        elif obj.is_featured:
            return format_html(
                '<span style="background: #8B5CF6; color: white; padding: 3px 8px; border-radius: 3px; font-weight: 500;">⭐ Featured</span>'
            )
        else:
            return format_html(
                '<span style="background: #10B981; color: white; padding: 3px 8px; border-radius: 3px; font-weight: 500;">✓ Approved</span>'
            )
    approval_status_display.short_description = 'Status'
    approval_status_display.admin_order_field = 'is_approved'
    
    def approve_reviews(self, request, queryset):
        updated = queryset.update(is_approved=True, is_flagged=False)
        self.message_user(request, f'{updated} review(s) approved.')
    approve_reviews.short_description = 'Approve selected reviews'
    
    def disapprove_reviews(self, request, queryset):
        updated = queryset.update(is_approved=False)
        self.message_user(request, f'{updated} review(s) disapproved.')
    disapprove_reviews.short_description = 'Disapprove selected reviews'
    
    def mark_as_featured(self, request, queryset):
        updated = queryset.update(is_featured=True, is_approved=True)
        self.message_user(request, f'{updated} review(s) marked as featured.')
    mark_as_featured.short_description = 'Mark as featured'
    
    def unmark_as_featured(self, request, queryset):
        updated = queryset.update(is_featured=False)
        self.message_user(request, f'{updated} review(s) unmarked as featured.')
    unmark_as_featured.short_description = 'Unmark as featured'
    
    def mark_as_verified(self, request, queryset):
        updated = queryset.update(is_verified_visit=True)
        self.message_user(request, f'{updated} review(s) marked as verified.')
    mark_as_verified.short_description = 'Mark as verified visit'
    
    def flag_reviews(self, request, queryset):
        updated = queryset.update(is_flagged=True)
        self.message_user(request, f'{updated} review(s) flagged.')
    flag_reviews.short_description = 'Flag selected reviews'
    
    def unflag_reviews(self, request, queryset):
        updated = queryset.update(is_flagged=False, flagged_reason='')
        self.message_user(request, f'{updated} review(s) unflagged.')
    unflag_reviews.short_description = 'Unflag selected reviews'
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related(
            'user',
            'vendor',
            'activity',
            'event',
            'location',
            'trip'
        )
        return queryset


@admin.register(ReviewResponse)
class ReviewResponseAdmin(admin.ModelAdmin):
    list_display = [
        'review_display',
        'responder',
        'responder_type',
        'is_approved',
        'created_at'
    ]
    list_filter = [
        'responder_type',
        'is_approved',
        'created_at'
    ]
    search_fields = [
        'response_text',
        'responder__username',
        'review__title',
        'review__user__username'
    ]
    autocomplete_fields = ['review', 'responder']
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    
    fieldsets = (
        ('Review', {
            'fields': ('review',)
        }),
        ('Responder', {
            'fields': ('responder', 'responder_type')
        }),
        ('Response', {
            'fields': ('response_text', 'is_approved')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at']
    
    actions = ['approve_responses', 'disapprove_responses']
    
    def review_display(self, obj):
        return format_html(
            '<div><strong>{}</strong></div>'
            '<div style="color: #6B7280; font-size: 12px;">by {}</div>',
            obj.review.get_review_target_name(),
            obj.review.user.username
        )
    review_display.short_description = 'Review'
    
    def approve_responses(self, request, queryset):
        updated = queryset.update(is_approved=True)
        self.message_user(request, f'{updated} response(s) approved.')
    approve_responses.short_description = 'Approve selected responses'
    
    def disapprove_responses(self, request, queryset):
        updated = queryset.update(is_approved=False)
        self.message_user(request, f'{updated} response(s) disapproved.')
    disapprove_responses.short_description = 'Disapprove selected responses'
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related(
            'review__user',
            'review__vendor',
            'review__activity',
            'review__event',
            'review__location',
            'review__trip',
            'responder'
        )
        return queryset


@admin.register(ReviewHelpful)
class ReviewHelpfulAdmin(admin.ModelAdmin):
    list_display = [
        'review_display',
        'user',
        'helpful_status_display',
        'created_at'
    ]
    list_filter = [
        'is_helpful',
        'created_at'
    ]
    search_fields = [
        'user__username',
        'review__title',
        'review__user__username'
    ]
    autocomplete_fields = ['review', 'user']
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    
    fieldsets = (
        ('Vote', {
            'fields': ('review', 'user', 'is_helpful')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at']
    
    def review_display(self, obj):
        stars = '⭐' * obj.review.rating
        return format_html(
            '<div>{} {}</div>'
            '<div style="color: #6B7280; font-size: 12px;">by {}</div>',
            stars,
            obj.review.get_review_target_name(),
            obj.review.user.username
        )
    review_display.short_description = 'Review'
    
    def helpful_status_display(self, obj):
        if obj.is_helpful:
            return format_html(
                '<span style="color: #10B981; font-weight: 500;">👍 Helpful</span>'
            )
        return format_html(
            '<span style="color: #EF4444; font-weight: 500;">👎 Not Helpful</span>'
        )
    helpful_status_display.short_description = 'Vote'
    helpful_status_display.admin_order_field = 'is_helpful'
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related(
            'review__user',
            'review__vendor',
            'review__activity',
            'review__event',
            'review__location',
            'review__trip',
            'user'
        )
        return queryset


@admin.register(ReviewReport)
class ReviewReportAdmin(admin.ModelAdmin):
    list_display = [
        'review_display',
        'reporter',
        'reason_display',
        'resolution_status_display',
        'created_at'
    ]
    list_filter = [
        'reason',
        'is_resolved',
        'created_at',
        'resolved_at'
    ]
    search_fields = [
        'details',
        'resolution_notes',
        'reporter__username',
        'review__title',
        'review__user__username'
    ]
    autocomplete_fields = ['review', 'reporter', 'resolved_by']
    date_hierarchy = 'created_at'
    ordering = ['is_resolved', '-created_at']
    
    fieldsets = (
        ('Report', {
            'fields': ('review', 'reporter', 'reason', 'details')
        }),
        ('Resolution', {
            'fields': (
                'is_resolved',
                'resolved_by',
                'resolved_at',
                'resolution_notes'
            )
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at']
    
    actions = ['mark_as_resolved', 'mark_as_unresolved']
    
    def review_display(self, obj):
        stars = '⭐' * obj.review.rating
        return format_html(
            '<div>{} {}</div>'
            '<div style="color: #6B7280; font-size: 12px;">by {}</div>',
            stars,
            obj.review.get_review_target_name(),
            obj.review.user.username
        )
    review_display.short_description = 'Review'
    
    def reason_display(self, obj):
        colors = {
            'spam': '#EF4444',
            'offensive': '#DC2626',
            'fake': '#F59E0B',
            'irrelevant': '#6B7280',
            'personal': '#8B5CF6',
            'other': '#3B82F6'
        }
        color = colors.get(obj.reason, '#6B7280')
        return format_html(
            '<span style="background: {}; color: white; padding: 3px 8px; border-radius: 3px; font-size: 11px; font-weight: 500;">{}</span>',
            color,
            obj.get_reason_display()
        )
    reason_display.short_description = 'Reason'
    reason_display.admin_order_field = 'reason'
    
    def resolution_status_display(self, obj):
        if obj.is_resolved:
            resolver = obj.resolved_by.username if obj.resolved_by else 'Unknown'
            return format_html(
                '<span style="background: #10B981; color: white; padding: 3px 8px; border-radius: 3px; font-weight: 500;">✓ Resolved</span>'
                '<div style="color: #6B7280; font-size: 11px; margin-top: 2px;">by {}</div>',
                resolver
            )
        return format_html(
            '<span style="background: #F59E0B; color: white; padding: 3px 8px; border-radius: 3px; font-weight: 500;">⏳ Pending</span>'
        )
    resolution_status_display.short_description = 'Status'
    resolution_status_display.admin_order_field = 'is_resolved'
    
    def mark_as_resolved(self, request, queryset):
        updated = queryset.update(
            is_resolved=True,
            resolved_by=request.user,
            resolved_at=timezone.now()
        )
        self.message_user(request, f'{updated} report(s) marked as resolved.')
    mark_as_resolved.short_description = 'Mark as resolved'
    
    def mark_as_unresolved(self, request, queryset):
        updated = queryset.update(
            is_resolved=False,
            resolved_by=None,
            resolved_at=None,
            resolution_notes=''
        )
        self.message_user(request, f'{updated} report(s) marked as unresolved.')
    mark_as_unresolved.short_description = 'Mark as unresolved'
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related(
            'review__user',
            'review__vendor',
            'review__activity',
            'review__event',
            'review__location',
            'review__trip',
            'reporter',
            'resolved_by'
        )
        return queryset