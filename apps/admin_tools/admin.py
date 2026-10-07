# admin_tools/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import (
    ModerationQueue, ReportedContent, UserActivityLog,
    SystemMetrics, ModeratorNote, AdminAction
)


@admin.register(ModerationQueue)
class ModerationQueueAdmin(admin.ModelAdmin):
    list_display = ['id', 'content_type', 'object_id', 'submitted_by', 'reason', 'priority', 'status', 'reviewed_by', 'created_at']
    list_filter = ['status', 'priority', 'reason', 'content_type', 'created_at']
    search_fields = ['submitted_by__username', 'reviewed_by__username', 'reason_details']
    readonly_fields = ['created_at', 'updated_at', 'reviewed_at']
    date_hierarchy = 'created_at'
    raw_id_fields = ['submitted_by', 'reviewed_by', 'escalated_to', 'content_type']
    
    fieldsets = (
        ('Content', {
            'fields': ('content_type', 'object_id', 'submitted_by')
        }),
        ('Moderation Info', {
            'fields': ('reason', 'reason_details', 'priority', 'status')
        }),
        ('Review', {
            'fields': ('reviewed_by', 'reviewed_at', 'review_notes', 'action_taken')
        }),
        ('Escalation', {
            'fields': ('escalated_to', 'escalation_reason'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_in_review', 'approve_items', 'reject_items']
    
    def mark_in_review(self, request, queryset):
        """Mark items as in review"""
        updated = queryset.filter(status='pending').update(status='in_review', reviewed_by=request.user)
        self.message_user(request, f'{updated} item(s) marked as in review.')
    mark_in_review.short_description = 'Mark as in review'
    
    def approve_items(self, request, queryset):
        """Approve selected items"""
        count = 0
        for item in queryset:
            item.approve(request.user, 'Bulk approved via admin')
            count += 1
        self.message_user(request, f'{count} item(s) approved.')
    approve_items.short_description = 'Approve selected items'
    
    def reject_items(self, request, queryset):
        """Reject selected items"""
        count = 0
        for item in queryset:
            item.reject(request.user, 'Bulk rejected via admin')
            count += 1
        self.message_user(request, f'{count} item(s) rejected.')
    reject_items.short_description = 'Reject selected items'


@admin.register(ReportedContent)
class ReportedContentAdmin(admin.ModelAdmin):
    list_display = ['id', 'reporter', 'content_type', 'object_id', 'reason', 'status', 'reviewed_by', 'created_at']
    list_filter = ['status', 'reason', 'content_type', 'requires_followup', 'created_at']
    search_fields = ['reporter__username', 'reviewed_by__username', 'description']
    readonly_fields = ['created_at', 'updated_at', 'reviewed_at']
    date_hierarchy = 'created_at'
    raw_id_fields = ['reporter', 'reviewed_by', 'content_type']
    
    fieldsets = (
        ('Report Info', {
            'fields': ('reporter', 'content_type', 'object_id')
        }),
        ('Details', {
            'fields': ('reason', 'description', 'evidence_urls')
        }),
        ('Status', {
            'fields': ('status', 'reviewed_by', 'reviewed_at', 'resolution_notes', 'action_taken')
        }),
        ('Follow-up', {
            'fields': ('requires_followup', 'followup_notes'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_investigating', 'mark_resolved', 'mark_dismissed']
    
    def mark_investigating(self, request, queryset):
        """Mark reports as under investigation"""
        from django.utils import timezone
        updated = queryset.filter(status='pending').update(
            status='investigating',
            reviewed_by=request.user,
            reviewed_at=timezone.now()
        )
        self.message_user(request, f'{updated} report(s) marked as investigating.')
    mark_investigating.short_description = 'Mark as investigating'
    
    def mark_resolved(self, request, queryset):
        """Mark reports as resolved"""
        from django.utils import timezone
        updated = queryset.exclude(status='resolved').update(
            status='resolved',
            reviewed_by=request.user,
            reviewed_at=timezone.now()
        )
        self.message_user(request, f'{updated} report(s) marked as resolved.')
    mark_resolved.short_description = 'Mark as resolved'
    
    def mark_dismissed(self, request, queryset):
        """Dismiss reports"""
        from django.utils import timezone
        updated = queryset.exclude(status='dismissed').update(
            status='dismissed',
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
            resolution_notes='Dismissed via admin bulk action'
        )
        self.message_user(request, f'{updated} report(s) dismissed.')
    mark_dismissed.short_description = 'Dismiss reports'


@admin.register(UserActivityLog)
class UserActivityLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'action_type', 'action_description', 'ip_address', 'device_type', 'created_at']
    list_filter = ['action_type', 'device_type', 'created_at']
    search_fields = ['user__username', 'user__email', 'action_description', 'ip_address']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'created_at'
    raw_id_fields = ['user', 'content_type']
    
    fieldsets = (
        ('User & Action', {
            'fields': ('user', 'action_type', 'action_description')
        }),
        ('Related Object', {
            'fields': ('content_type', 'object_id'),
            'classes': ('collapse',)
        }),
        ('Technical Details', {
            'fields': ('ip_address', 'user_agent', 'device_type')
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        """Prevent manual addition of logs"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Prevent editing of logs"""
        return False


@admin.register(SystemMetrics)
class SystemMetricsAdmin(admin.ModelAdmin):
    list_display = ['date', 'total_users', 'new_users_today', 'active_users_today', 'total_trips', 'revenue_today']
    list_filter = ['date']
    search_fields = ['date']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'date'
    
    fieldsets = (
        ('Date', {
            'fields': ('date',)
        }),
        ('User Metrics', {
            'fields': ('total_users', 'new_users_today', 'active_users_today', 'premium_users')
        }),
        ('Content Metrics', {
            'fields': (
                'total_trips', 'trips_created_today',
                'total_bucket_list_items', 'bucket_list_items_added_today',
                'total_reviews', 'reviews_created_today'
            )
        }),
        ('Engagement Metrics', {
            'fields': ('total_page_views', 'total_sessions', 'avg_session_duration')
        }),
        ('Activity Metrics', {
            'fields': ('total_activities', 'total_events', 'total_locations', 'total_vendors')
        }),
        ('Moderation Metrics', {
            'fields': ('pending_moderation_count', 'reports_resolved_today')
        }),
        ('System Health', {
            'fields': ('avg_response_time', 'error_count')
        }),
        ('Revenue', {
            'fields': ('revenue_today',)
        }),
        ('Custom Metrics', {
            'fields': ('custom_metrics',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        """Prevent manual addition (should be auto-generated)"""
        return False


@admin.register(ModeratorNote)
class ModeratorNoteAdmin(admin.ModelAdmin):
    list_display = ['id', 'author', 'note_preview', 'is_pinned', 'is_internal', 'created_at']
    list_filter = ['is_pinned', 'is_internal', 'created_at']
    search_fields = ['author__username', 'note']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'created_at'
    raw_id_fields = ['author', 'content_type']
    
    fieldsets = (
        ('Author & Subject', {
            'fields': ('author', 'content_type', 'object_id')
        }),
        ('Note', {
            'fields': ('note',)
        }),
        ('Settings', {
            'fields': ('is_internal', 'is_pinned')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def note_preview(self, obj):
        """Show truncated note"""
        return obj.note[:100] + '...' if len(obj.note) > 100 else obj.note
    note_preview.short_description = 'Note'
    
    actions = ['pin_notes', 'unpin_notes']
    
    def pin_notes(self, request, queryset):
        """Pin selected notes"""
        updated = queryset.update(is_pinned=True)
        self.message_user(request, f'{updated} note(s) pinned.')
    pin_notes.short_description = 'Pin selected notes'
    
    def unpin_notes(self, request, queryset):
        """Unpin selected notes"""
        updated = queryset.update(is_pinned=False)
        self.message_user(request, f'{updated} note(s) unpinned.')
    unpin_notes.short_description = 'Unpin selected notes'


@admin.register(AdminAction)
class AdminActionAdmin(admin.ModelAdmin):
    list_display = ['id', 'admin', 'action_type', 'description_preview', 'ip_address', 'created_at']
    list_filter = ['action_type', 'created_at']
    search_fields = ['admin__username', 'description', 'reason']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'created_at'
    raw_id_fields = ['admin', 'content_type']
    
    fieldsets = (
        ('Admin & Action', {
            'fields': ('admin', 'action_type', 'description')
        }),
        ('Affected Object', {
            'fields': ('content_type', 'object_id'),
            'classes': ('collapse',)
        }),
        ('State Changes', {
            'fields': ('before_state', 'after_state'),
            'classes': ('collapse',)
        }),
        ('Context', {
            'fields': ('reason', 'ip_address')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def description_preview(self, obj):
        """Show truncated description"""
        return obj.description[:100] + '...' if len(obj.description) > 100 else obj.description
    description_preview.short_description = 'Description'
    
    def has_add_permission(self, request):
        """Prevent manual addition of audit logs"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Prevent editing of audit logs"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of audit logs"""
        return False