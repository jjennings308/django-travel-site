# approval_system/admin.py
"""
Admin interface for the approval system.
Provides management of logs, rules, queues, and settings.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Count
from .models import (
    ApprovalLog, ApprovalRule, ApprovalQueue, 
    ApprovalSettings, ApprovalStatus
)


@admin.register(ApprovalLog)
class ApprovalLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'action_badge', 'content_info', 'performed_by', 
                    'status_change', 'created_at']
    list_filter = ['action', 'new_status', 'created_at', 'content_type']
    search_fields = ['notes', 'performed_by__username']
    readonly_fields = ['content_type', 'object_id', 'action', 'performed_by',
                      'old_status', 'new_status', 'notes', 'metadata', 
                      'ip_address', 'created_at']
    date_hierarchy = 'created_at'
    
    def action_badge(self, obj):
        colors = {
            'submitted': '#17a2b8',
            'approved': '#28a745',
            'rejected': '#dc3545',
            'changes_requested': '#ffc107',
            'archived': '#6c757d',
        }
        color = colors.get(obj.action, '#007bff')
        return format_html(
            '<span style="background: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 0.85em; font-weight: bold;">{}</span>',
            color,
            obj.get_action_display()
        )
    action_badge.short_description = 'Action'
    
    def content_info(self, obj):
        if obj.content_object:
            return format_html(
                '{}<br><small style="color: #666;">{}</small>',
                str(obj.content_object),
                obj.content_type
            )
        return format_html(
            '<span style="color: #999;">Deleted</span><br>'
            '<small style="color: #666;">{}</small>',
            obj.content_type
        )
    content_info.short_description = 'Content'
    
    def status_change(self, obj):
        if obj.old_status and obj.new_status:
            return format_html(
                '{} → {}',
                obj.get_old_status_display(),
                obj.get_new_status_display()
            )
        elif obj.new_status:
            return obj.get_new_status_display()
        return '-'
    status_change.short_description = 'Status Change'
    
    def has_add_permission(self, request):
        # Logs are created automatically, don't allow manual creation
        return False
    
    def has_change_permission(self, request, obj=None):
        # Logs should not be editable
        return False


@admin.register(ApprovalRule)
class ApprovalRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'content_type', 'is_active', 'priority', 
                    'auto_approve', 'auto_reject', 'assign_to_user']
    list_filter = ['is_active', 'auto_approve', 'auto_reject', 'content_type']
    search_fields = ['name', 'description']
    ordering = ['-priority', 'name']
    
    fieldsets = [
        ('Basic Information', {
            'fields': ('name', 'description', 'content_type', 'is_active', 'priority')
        }),
        ('Auto-Actions', {
            'fields': ('auto_approve', 'auto_reject'),
            'description': 'Automatically approve or reject based on conditions'
        }),
        ('Routing', {
            'fields': ('assign_to_user',),
            'description': 'Assign matching items to specific reviewers'
        }),
        ('Conditions', {
            'fields': ('conditions',),
            'description': 'JSON conditions that must be met (see documentation)',
            'classes': ('collapse',)
        }),
    ]


@admin.register(ApprovalQueue)
class ApprovalQueueAdmin(admin.ModelAdmin):
    list_display = ['name', 'color_badge', 'status_filter', 'priority_filter',
                    'pending_count', 'reviewer_count', 'is_active']
    list_filter = ['is_active', 'status_filter', 'priority_filter']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ['reviewers', 'content_types']
    ordering = ['display_order', 'name']
    
    fieldsets = [
        ('Basic Information', {
            'fields': ('name', 'slug', 'description', 'is_active', 'display_order')
        }),
        ('Filters', {
            'fields': ('content_types', 'status_filter', 'priority_filter')
        }),
        ('Reviewers', {
            'fields': ('reviewers',)
        }),
        ('Display Settings', {
            'fields': ('color', 'icon'),
            'classes': ('collapse',)
        }),
    ]
    
    def color_badge(self, obj):
        return format_html(
            '<span style="background: {}; color: white; padding: 4px 12px; '
            'border-radius: 3px; font-weight: bold;">{}</span>',
            obj.color,
            obj.icon if obj.icon else '●'
        )
    color_badge.short_description = 'Display'
    
    def pending_count(self, obj):
        count = obj.get_pending_count()
        if count > 0:
            return format_html(
                '<strong style="color: #dc3545;">{}</strong>',
                count
            )
        return count
    pending_count.short_description = 'Pending'
    
    def reviewer_count(self, obj):
        return obj.reviewers.count()
    reviewer_count.short_description = 'Reviewers'


@admin.register(ApprovalSettings)
class ApprovalSettingsAdmin(admin.ModelAdmin):
    
    fieldsets = [
        ('Notifications', {
            'fields': (
                'notify_on_submission',
                'notify_on_approval',
                'notify_on_rejection'
            )
        }),
        ('Automation', {
            'fields': ('auto_archive_rejected_days',)
        }),
        ('Review SLA', {
            'fields': ('review_sla_hours',),
            'description': 'Expected time to review items (for metrics and alerts)'
        }),
        ('Dashboard Settings', {
            'fields': ('items_per_page', 'show_archived_in_search')
        }),
    ]
    
    def has_add_permission(self, request):
        # Only one settings instance allowed
        return False
    
    def has_delete_permission(self, request, obj=None):
        # Don't allow deletion of settings
        return False


# Custom admin actions for models that use Approvable mixin
class ApprovableAdminMixin:
    """
    Mixin for admin classes of models that inherit from Approvable.
    Adds bulk approval actions and enhanced display.
    """
    
    def get_list_display(self, request):
        """Add approval fields to list display"""
        display = super().get_list_display(request)
        approval_fields = ['approval_status_badge', 'submitted_by', 'reviewed_by']
        
        # Insert after the first field
        if len(display) > 1:
            return [display[0]] + approval_fields + list(display[1:])
        return approval_fields + list(display)
    
    def get_list_filter(self, request):
        """Add approval filters"""
        filters = super().get_list_filter(request)
        approval_filters = ['approval_status', 'approval_priority', 'submitted_at']
        return list(filters) + approval_filters
    
    def get_readonly_fields(self, request, obj=None):
        """Make approval tracking fields readonly"""
        readonly = super().get_readonly_fields(request, obj)
        approval_readonly = ['submitted_by', 'submitted_at', 'reviewed_by', 'reviewed_at']
        return list(readonly) + approval_readonly
    
    actions = ['approve_selected', 'reject_selected', 'request_changes_selected']
    
    def approval_status_badge(self, obj):
        """Display approval status as colored badge"""
        colors = {
            'draft': '#6c757d',
            'pending': '#FFA500',
            'approved': '#28a745',
            'rejected': '#dc3545',
            'changes_requested': '#ffc107',
            'archived': '#6c757d',
        }
        color = colors.get(obj.approval_status, '#007bff')
        return format_html(
            '<span style="background: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px; font-weight: bold; font-size: 0.85em;">{}</span>',
            color,
            obj.get_approval_status_display()
        )
    approval_status_badge.short_description = 'Status'
    approval_status_badge.admin_order_field = 'approval_status'
    
    def approve_selected(self, request, queryset):
        """Bulk approve selected items"""
        count = 0
        for obj in queryset:
            if obj.approval_status != ApprovalStatus.APPROVED:
                obj.approve(request.user, f'Bulk approved by {request.user.username}')
                count += 1
        
        self.message_user(
            request,
            f'{count} item(s) approved successfully.',
            level='SUCCESS'
        )
    approve_selected.short_description = 'Approve selected items'
    
    def reject_selected(self, request, queryset):
        """Bulk reject selected items"""
        count = 0
        for obj in queryset:
            if obj.approval_status != ApprovalStatus.REJECTED:
                obj.reject(request.user, f'Bulk rejected by {request.user.username}')
                count += 1
        
        self.message_user(
            request,
            f'{count} item(s) rejected.',
            level='WARNING'
        )
    reject_selected.short_description = 'Reject selected items'
    
    def request_changes_selected(self, request, queryset):
        """Bulk request changes for selected items"""
        count = 0
        for obj in queryset:
            if obj.approval_status != ApprovalStatus.CHANGES_REQUESTED:
                obj.request_changes(request.user, 'Changes requested')
                count += 1
        
        self.message_user(
            request,
            f'{count} item(s) marked as needing changes.',
            level='INFO'
        )
    request_changes_selected.short_description = 'Request changes for selected items'


# Example usage for your location models:
# 
# from approval_system.admin import ApprovableAdminMixin
# 
# @admin.register(City)
# class CityAdmin(ApprovableAdminMixin, admin.ModelAdmin):
#     # your existing admin config
#     pass
