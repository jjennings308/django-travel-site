# notifications/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import (
    NotificationCategory, NotificationType, Notification,
    UserNotificationPreference, NotificationDigest,
    NotificationTemplate, PushDevice
)


@admin.register(NotificationCategory)
class NotificationCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'default_enabled', 'display_order', 'created_at']
    list_filter = ['default_enabled']
    search_fields = ['name', 'description']
    ordering = ['display_order', 'name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'icon', 'color')
        }),
        ('Settings', {
            'fields': ('default_enabled', 'display_order')
        }),
    )


@admin.register(NotificationType)
class NotificationTypeAdmin(admin.ModelAdmin):
    list_display = ['display_name', 'category', 'name', 'priority', 'is_system', 'created_at']
    list_filter = ['category', 'priority', 'is_system', 'default_email', 'default_push']
    search_fields = ['name', 'display_name', 'description']
    ordering = ['category', 'display_name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('category', 'name', 'display_name', 'description')
        }),
        ('Templates', {
            'fields': ('title_template', 'message_template')
        }),
        ('Default Channels', {
            'fields': ('default_email', 'default_push', 'default_in_app')
        }),
        ('Settings', {
            'fields': ('priority', 'is_system')
        }),
    )


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'notification_type', 'title_preview', 'is_read', 'channels_display', 'created_at']
    list_filter = ['is_read', 'is_archived', 'notification_type', 'email_sent', 'push_sent', 'created_at']
    search_fields = ['user__username', 'user__email', 'title', 'message']
    readonly_fields = ['created_at', 'updated_at', 'read_at', 'archived_at', 'email_sent_at', 'email_opened_at', 'push_sent_at']
    date_hierarchy = 'created_at'
    raw_id_fields = ['user', 'content_type']
    
    fieldsets = (
        ('User & Type', {
            'fields': ('user', 'notification_type')
        }),
        ('Content', {
            'fields': ('title', 'message', 'action_url')
        }),
        ('Related Object', {
            'fields': ('content_type', 'object_id'),
            'classes': ('collapse',)
        }),
        ('Delivery', {
            'fields': ('channels', 'scheduled_for', 'expires_at')
        }),
        ('Status', {
            'fields': ('is_read', 'read_at', 'is_archived', 'archived_at')
        }),
        ('Email Tracking', {
            'fields': ('email_sent', 'email_sent_at', 'email_opened', 'email_opened_at'),
            'classes': ('collapse',)
        }),
        ('Push Tracking', {
            'fields': ('push_sent', 'push_sent_at'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('metadata', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_as_read', 'mark_as_unread', 'archive_notifications']
    
    def title_preview(self, obj):
        """Show truncated title"""
        return obj.title[:50] + '...' if len(obj.title) > 50 else obj.title
    title_preview.short_description = 'Title'
    
    def channels_display(self, obj):
        """Display channels as badges"""
        badges = []
        for channel in obj.channels:
            color = {
                'in_app': 'blue',
                'email': 'green',
                'push': 'orange',
                'sms': 'purple'
            }.get(channel, 'gray')
            badges.append(f'<span style="background-color:{color};color:white;padding:2px 6px;border-radius:3px;margin-right:3px;">{channel}</span>')
        return format_html(''.join(badges))
    channels_display.short_description = 'Channels'
    
    def mark_as_read(self, request, queryset):
        """Mark selected notifications as read"""
        from django.utils import timezone
        updated = queryset.filter(is_read=False).update(is_read=True, read_at=timezone.now())
        self.message_user(request, f'{updated} notification(s) marked as read.')
    mark_as_read.short_description = 'Mark selected as read'
    
    def mark_as_unread(self, request, queryset):
        """Mark selected notifications as unread"""
        updated = queryset.filter(is_read=True).update(is_read=False, read_at=None)
        self.message_user(request, f'{updated} notification(s) marked as unread.')
    mark_as_unread.short_description = 'Mark selected as unread'
    
    def archive_notifications(self, request, queryset):
        """Archive selected notifications"""
        from django.utils import timezone
        updated = queryset.filter(is_archived=False).update(is_archived=True, archived_at=timezone.now())
        self.message_user(request, f'{updated} notification(s) archived.')
    archive_notifications.short_description = 'Archive selected notifications'


@admin.register(UserNotificationPreference)
class UserNotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ['user', 'notification_type', 'email_enabled', 'push_enabled', 'in_app_enabled', 'frequency']
    list_filter = ['email_enabled', 'push_enabled', 'in_app_enabled', 'frequency', 'notification_type__category']
    search_fields = ['user__username', 'user__email', 'notification_type__display_name']
    raw_id_fields = ['user']
    
    fieldsets = (
        ('User & Type', {
            'fields': ('user', 'notification_type')
        }),
        ('Channel Preferences', {
            'fields': ('email_enabled', 'push_enabled', 'in_app_enabled', 'sms_enabled')
        }),
        ('Frequency', {
            'fields': ('frequency',)
        }),
        ('Quiet Hours', {
            'fields': ('quiet_hours_enabled', 'quiet_hours_start', 'quiet_hours_end'),
            'classes': ('collapse',)
        }),
    )


@admin.register(NotificationDigest)
class NotificationDigestAdmin(admin.ModelAdmin):
    list_display = ['user', 'digest_type', 'period_start', 'period_end', 'notification_count', 'is_sent', 'sent_at']
    list_filter = ['digest_type', 'is_sent', 'period_start']
    search_fields = ['user__username', 'user__email']
    date_hierarchy = 'period_end'
    readonly_fields = ['created_at', 'updated_at']
    raw_id_fields = ['user']
    
    fieldsets = (
        ('Digest Info', {
            'fields': ('user', 'digest_type')
        }),
        ('Period', {
            'fields': ('period_start', 'period_end', 'notification_count')
        }),
        ('Status', {
            'fields': ('is_sent', 'sent_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ['notification_type', 'template_type', 'version', 'is_active', 'created_at']
    list_filter = ['template_type', 'is_active', 'notification_type__category']
    search_fields = ['notification_type__display_name', 'content']
    ordering = ['notification_type', 'template_type', '-version']
    
    fieldsets = (
        ('Template Info', {
            'fields': ('notification_type', 'template_type', 'version')
        }),
        ('Content', {
            'fields': ('content',)
        }),
        ('Variables', {
            'fields': ('available_variables',),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )
    
    actions = ['activate_templates', 'deactivate_templates']
    
    def activate_templates(self, request, queryset):
        """Activate selected templates"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} template(s) activated.')
    activate_templates.short_description = 'Activate selected templates'
    
    def deactivate_templates(self, request, queryset):
        """Deactivate selected templates"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} template(s) deactivated.')
    deactivate_templates.short_description = 'Deactivate selected templates'


@admin.register(PushDevice)
class PushDeviceAdmin(admin.ModelAdmin):
    list_display = ['user', 'device_type', 'device_name', 'is_active', 'last_used_at', 'created_at']
    list_filter = ['device_type', 'is_active', 'created_at']
    search_fields = ['user__username', 'user__email', 'device_name', 'device_token']
    readonly_fields = ['last_used_at', 'created_at', 'updated_at']
    raw_id_fields = ['user']
    
    fieldsets = (
        ('Device Info', {
            'fields': ('user', 'device_type', 'device_name')
        }),
        ('Token', {
            'fields': ('device_token',)
        }),
        ('Technical Details', {
            'fields': ('app_version', 'os_version'),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('is_active', 'last_used_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['activate_devices', 'deactivate_devices']
    
    def activate_devices(self, request, queryset):
        """Activate selected devices"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} device(s) activated.')
    activate_devices.short_description = 'Activate selected devices'
    
    def deactivate_devices(self, request, queryset):
        """Deactivate selected devices"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} device(s) deactivated.')
    deactivate_devices.short_description = 'Deactivate selected devices'