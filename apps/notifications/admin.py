from django.contrib import admin
from django.utils.html import format_html_join

from .models import (
    Notification,
    NotificationCategory,
    NotificationType,
    UserNotificationPreference,
)


@admin.register(NotificationCategory)
class NotificationCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "display_order", "created_at"]
    search_fields = ["name", "description"]
    ordering = ["display_order", "name"]

    fieldsets = (
        ("Basic Information", {"fields": ("name", "description", "icon", "color")}),
        ("Settings", {"fields": ("display_order",)}),
    )


@admin.register(NotificationType)
class NotificationTypeAdmin(admin.ModelAdmin):
    list_display = ["display_name", "category", "name", "priority", "default_email", "created_at"]
    list_filter = ["category", "priority", "default_email"]
    search_fields = ["name", "display_name", "description"]
    ordering = ["category", "display_name"]

    fieldsets = (
        ("Basic Information", {"fields": ("category", "name", "display_name", "description")}),
        ("Settings", {"fields": ("default_email", "priority")}),
    )


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "notification_type", "title_preview", "is_read", "channels_display", "created_at"]
    list_filter = ["is_read", "is_archived", "notification_type", "email_sent", "created_at"]
    search_fields = ["user__username", "user__email", "title", "message"]
    readonly_fields = ["created_at", "updated_at", "read_at", "archived_at", "email_sent_at"]
    date_hierarchy = "created_at"
    raw_id_fields = ["user", "content_type"]

    fieldsets = (
        ("User & Type", {"fields": ("user", "notification_type")}),
        ("Content", {"fields": ("title", "message", "action_url")}),
        ("Related Object", {"fields": ("content_type", "object_id"), "classes": ("collapse",)}),
        ("Delivery", {"fields": ("channels", "expires_at")}),
        ("Status", {"fields": ("is_read", "read_at", "is_archived", "archived_at")}),
        ("Email Tracking", {"fields": ("email_sent", "email_sent_at"), "classes": ("collapse",)}),
        ("Metadata", {"fields": ("metadata", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    actions = ["mark_as_read", "mark_as_unread", "archive_notifications"]

    def title_preview(self, obj):
        """Show truncated title"""
        return obj.title[:50] + "..." if len(obj.title) > 50 else obj.title

    title_preview.short_description = "Title"

    def channels_display(self, obj):
        """Display channels as badges"""
        colors = {"in_app": "blue", "email": "green"}
        return format_html_join(
            "",
            '<span style="background-color:{};color:white;padding:2px 6px;border-radius:3px;margin-right:3px;">{}</span>',
            ((colors.get(channel, "gray"), channel) for channel in obj.channels),
        )

    channels_display.short_description = "Channels"

    def mark_as_read(self, request, queryset):
        """Mark selected notifications as read"""
        from django.utils import timezone

        updated = queryset.filter(is_read=False).update(is_read=True, read_at=timezone.now())
        self.message_user(request, f"{updated} notification(s) marked as read.")

    mark_as_read.short_description = "Mark selected as read"

    def mark_as_unread(self, request, queryset):
        """Mark selected notifications as unread"""
        updated = queryset.filter(is_read=True).update(is_read=False, read_at=None)
        self.message_user(request, f"{updated} notification(s) marked as unread.")

    mark_as_unread.short_description = "Mark selected as unread"

    def archive_notifications(self, request, queryset):
        """Archive selected notifications"""
        from django.utils import timezone

        updated = queryset.filter(is_archived=False).update(is_archived=True, archived_at=timezone.now())
        self.message_user(request, f"{updated} notification(s) archived.")

    archive_notifications.short_description = "Archive selected notifications"


@admin.register(UserNotificationPreference)
class UserNotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ["user", "notification_type", "email_enabled"]
    list_filter = ["email_enabled", "notification_type__category"]
    search_fields = ["user__username", "user__email", "notification_type__display_name"]
    raw_id_fields = ["user"]

    fieldsets = (
        ("User & Type", {"fields": ("user", "notification_type")}),
        ("Email", {"fields": ("email_enabled",)}),
    )
