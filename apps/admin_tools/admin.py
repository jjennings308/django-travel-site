# admin_tools/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import ReportedContent


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
