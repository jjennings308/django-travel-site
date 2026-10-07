# recommendations/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import (
    RecommendationRule, Recommendation, UserInterest,
    RecommendationFeedback, RecommendationPerformance
)


@admin.register(RecommendationRule)
class RecommendationRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'rule_type', 'source_content_type', 'target_content_type', 'priority', 'is_active', 'performance_display']
    list_filter = ['rule_type', 'is_active', 'priority', 'source_content_type', 'target_content_type']
    search_fields = ['name', 'description']
    readonly_fields = ['usage_count', 'average_ctr', 'created_at', 'updated_at']
    ordering = ['-priority', 'name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'rule_type')
        }),
        ('Content Types', {
            'fields': ('source_content_type', 'target_content_type')
        }),
        ('Scoring', {
            'fields': ('base_score', 'weight')
        }),
        ('Conditions', {
            'fields': ('conditions',),
            'classes': ('collapse',)
        }),
        ('Settings', {
            'fields': ('is_active', 'max_recommendations', 'priority')
        }),
        ('Performance', {
            'fields': ('usage_count', 'average_ctr'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['activate_rules', 'deactivate_rules']
    
    def performance_display(self, obj):
        """Display performance metrics"""
        ctr_percent = obj.average_ctr * 100
        color = 'green' if ctr_percent > 5 else 'orange' if ctr_percent > 2 else 'red'
        return format_html(
            '<span style="color:{};">CTR: {:.2f}% | Used: {} times</span>',
            color, ctr_percent, obj.usage_count
        )
    performance_display.short_description = 'Performance'
    
    def activate_rules(self, request, queryset):
        """Activate selected rules"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} rule(s) activated.')
    activate_rules.short_description = 'Activate selected rules'
    
    def deactivate_rules(self, request, queryset):
        """Deactivate selected rules"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} rule(s) deactivated.')
    deactivate_rules.short_description = 'Deactivate selected rules'


@admin.register(Recommendation)
class RecommendationAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'content_type', 'object_id', 'relevance_score', 'engagement_display', 'created_at']
    list_filter = ['generation_method', 'is_viewed', 'is_clicked', 'is_converted', 'is_dismissed', 'content_type', 'created_at']
    search_fields = ['user__username', 'user__email', 'reason']
    readonly_fields = ['created_at', 'updated_at', 'viewed_at', 'clicked_at', 'dismissed_at', 'saved_at', 'converted_at']
    date_hierarchy = 'created_at'
    raw_id_fields = ['user', 'content_type', 'context_content_type', 'rule']
    
    fieldsets = (
        ('User & Content', {
            'fields': ('user', 'content_type', 'object_id')
        }),
        ('Context', {
            'fields': ('context_content_type', 'context_object_id'),
            'classes': ('collapse',)
        }),
        ('Scoring', {
            'fields': ('relevance_score', 'confidence_score')
        }),
        ('Source', {
            'fields': ('rule', 'generation_method', 'reason')
        }),
        ('Explanation', {
            'fields': ('explanation_data',),
            'classes': ('collapse',)
        }),
        ('Engagement', {
            'fields': ('is_viewed', 'viewed_at', 'is_clicked', 'clicked_at', 'is_saved', 'saved_at')
        }),
        ('Conversion', {
            'fields': ('is_converted', 'converted_at')
        }),
        ('Dismissal', {
            'fields': ('is_dismissed', 'dismissed_at', 'dismiss_reason'),
            'classes': ('collapse',)
        }),
        ('Display', {
            'fields': ('display_position', 'expires_at'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def engagement_display(self, obj):
        """Display engagement metrics"""
        badges = []
        if obj.is_viewed:
            badges.append('<span style="background-color:blue;color:white;padding:2px 6px;border-radius:3px;margin-right:3px;">Viewed</span>')
        if obj.is_clicked:
            badges.append('<span style="background-color:green;color:white;padding:2px 6px;border-radius:3px;margin-right:3px;">Clicked</span>')
        if obj.is_converted:
            badges.append('<span style="background-color:purple;color:white;padding:2px 6px;border-radius:3px;margin-right:3px;">Converted</span>')
        if obj.is_dismissed:
            badges.append('<span style="background-color:red;color:white;padding:2px 6px;border-radius:3px;margin-right:3px;">Dismissed</span>')
        return format_html(''.join(badges)) if badges else '-'
    engagement_display.short_description = 'Engagement'


@admin.register(UserInterest)
class UserInterestAdmin(admin.ModelAdmin):
    list_display = ['user', 'content_type', 'object_id', 'interest_score', 'source', 'interaction_count', 'last_interacted_at']
    list_filter = ['source', 'content_type', 'last_interacted_at']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['last_interacted_at', 'created_at', 'updated_at']
    raw_id_fields = ['user', 'content_type']
    
    fieldsets = (
        ('User & Content', {
            'fields': ('user', 'content_type', 'object_id')
        }),
        ('Interest', {
            'fields': ('interest_score', 'source')
        }),
        ('Tracking', {
            'fields': ('view_count', 'interaction_count', 'last_interacted_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(RecommendationFeedback)
class RecommendationFeedbackAdmin(admin.ModelAdmin):
    list_display = ['user', 'recommendation', 'feedback_type', 'comment_preview', 'created_at']
    list_filter = ['feedback_type', 'created_at']
    search_fields = ['user__username', 'comment']
    readonly_fields = ['created_at', 'updated_at']
    raw_id_fields = ['user', 'recommendation']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Feedback', {
            'fields': ('recommendation', 'user', 'feedback_type')
        }),
        ('Details', {
            'fields': ('comment',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def comment_preview(self, obj):
        """Show truncated comment"""
        if obj.comment:
            return obj.comment[:50] + '...' if len(obj.comment) > 50 else obj.comment
        return '-'
    comment_preview.short_description = 'Comment'


@admin.register(RecommendationPerformance)
class RecommendationPerformanceAdmin(admin.ModelAdmin):
    list_display = ['rule', 'period_start', 'period_end', 'total_generated', 'ctr_display', 'conversion_display']
    list_filter = ['rule', 'period_start']
    search_fields = ['rule__name']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'period_end'
    
    fieldsets = (
        ('Rule & Period', {
            'fields': ('rule', 'period_start', 'period_end')
        }),
        ('Volume Metrics', {
            'fields': ('total_generated', 'total_viewed', 'total_clicked', 'total_converted', 'total_dismissed')
        }),
        ('Rate Metrics', {
            'fields': ('view_rate', 'click_through_rate', 'conversion_rate')
        }),
        ('Score Metrics', {
            'fields': ('avg_relevance_score', 'avg_confidence_score')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def ctr_display(self, obj):
        """Display CTR with color coding"""
        ctr_percent = obj.click_through_rate * 100
        color = 'green' if ctr_percent > 5 else 'orange' if ctr_percent > 2 else 'red'
        return format_html('<span style="color:{};">{:.2f}%</span>', color, ctr_percent)
    ctr_display.short_description = 'CTR'
    
    def conversion_display(self, obj):
        """Display conversion rate with color coding"""
        conv_percent = obj.conversion_rate * 100
        color = 'green' if conv_percent > 10 else 'orange' if conv_percent > 5 else 'red'
        return format_html('<span style="color:{};">{:.2f}%</span>', color, conv_percent)
    conversion_display.short_description = 'Conversion Rate'