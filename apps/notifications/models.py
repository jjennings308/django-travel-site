"""In-app notifications (the bell, /notifications/) and their emails, sent by ``services.notify()``, with a
per-person, per-kind email switch (``UserNotificationPreference.email_enabled``). Push, SMS, quiet hours,
frequency, digests and editable templates were never built and were removed (notifications 0006, NC1)."""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.models import TimeStampedModel


class NotificationCategory(TimeStampedModel):
    """Categories for organizing notification types"""

    name = models.CharField(max_length=100, unique=True, help_text="E.g., Trips, Bucket List, Social, System")
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)
    color = models.CharField(max_length=7, default="#3B82F6", help_text="Hex color code")

    display_order = models.IntegerField(default=0)

    class Meta:
        db_table = "notification_categories"
        verbose_name_plural = "Notification Categories"
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name


class NotificationType(TimeStampedModel):
    """Specific notification types within categories"""

    category = models.ForeignKey(NotificationCategory, on_delete=models.CASCADE, related_name="types")

    name = models.CharField(
        max_length=100, unique=True, help_text="E.g., trip_reminder, bucket_list_milestone, new_review"
    )

    display_name = models.CharField(max_length=200, help_text="User-friendly name")

    description = models.TextField(blank=True, help_text="Description of when this notification is sent")

    # Default settings
    default_email = models.BooleanField(default=True, help_text="Send email by default")

    priority = models.CharField(
        max_length=20,
        choices=[("low", "Low"), ("normal", "Normal"), ("high", "High"), ("urgent", "Urgent")],
        default="normal",
    )

    class Meta:
        db_table = "notification_types"
        ordering = ["category", "display_name"]

    def __str__(self):
        return f"{self.category.name} - {self.display_name}"


class Notification(TimeStampedModel):
    """Individual notifications sent to users"""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")

    notification_type = models.ForeignKey(NotificationType, on_delete=models.CASCADE, related_name="notifications")

    # Content
    title = models.CharField(max_length=200)
    message = models.TextField()

    # Related object (generic relation)
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True, blank=True, help_text="Type of related object"
    )
    object_id = models.PositiveIntegerField(null=True, blank=True, help_text="ID of related object")
    content_object = GenericForeignKey("content_type", "object_id")

    # Action URL
    action_url = models.CharField(
        max_length=500, blank=True, help_text="URL to navigate to when notification is clicked"
    )

    # Delivery channels
    CHANNEL_CHOICES = [
        ("in_app", "In-App"),
        ("email", "Email"),
    ]
    channels = models.JSONField(default=list, help_text="List of channels this notification was sent through")

    # Status
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    is_archived = models.BooleanField(default=False, help_text="User has archived this notification")
    archived_at = models.DateTimeField(null=True, blank=True)

    # Delivery status
    email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)

    # Metadata
    metadata = models.JSONField(default=dict, blank=True, help_text="Additional data for the notification")

    # Expiration
    expires_at = models.DateTimeField(null=True, blank=True, help_text="When notification becomes irrelevant")

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["user", "is_read"]),
            models.Index(fields=["notification_type", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.user.username}: {self.title}"

    def mark_as_read(self):
        """Mark notification as read"""
        if not self.is_read:
            from django.utils import timezone

            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])

    def archive(self):
        """Archive notification"""
        if not self.is_archived:
            from django.utils import timezone

            self.is_archived = True
            self.archived_at = timezone.now()
            self.save(update_fields=["is_archived", "archived_at"])

    @property
    def is_expired(self):
        """Check if notification has expired"""
        if self.expires_at:
            from django.utils import timezone

            return timezone.now() > self.expires_at
        return False


class UserNotificationPreference(TimeStampedModel):
    """User preferences for notification types"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preferences"
    )

    notification_type = models.ForeignKey(NotificationType, on_delete=models.CASCADE, related_name="user_preferences")

    # Email on or off for this kind (the unsubscribe link sets it; services.wants_email reads it)
    email_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "user_notification_preferences"
        unique_together = [["user", "notification_type"]]
        ordering = ["user", "notification_type"]

    def __str__(self):
        return f"{self.user.username} - {self.notification_type.display_name}"
