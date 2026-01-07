# notifications/models.py
from django.db import models
from core.models import TimeStampedModel
from accounts.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType


class NotificationCategory(TimeStampedModel):
    """Categories for organizing notification types"""
    
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="E.g., Trips, Bucket List, Social, System"
    )
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)
    color = models.CharField(
        max_length=7,
        default='#3B82F6',
        help_text="Hex color code"
    )
    
    # Default settings
    default_enabled = models.BooleanField(
        default=True,
        help_text="Whether this category is enabled by default for new users"
    )
    
    display_order = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'notification_categories'
        verbose_name_plural = 'Notification Categories'
        ordering = ['display_order', 'name']
    
    def __str__(self):
        return self.name


class NotificationType(TimeStampedModel):
    """Specific notification types within categories"""
    
    category = models.ForeignKey(
        NotificationCategory,
        on_delete=models.CASCADE,
        related_name='types'
    )
    
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="E.g., trip_reminder, bucket_list_milestone, new_review"
    )
    
    display_name = models.CharField(
        max_length=200,
        help_text="User-friendly name"
    )
    
    description = models.TextField(
        blank=True,
        help_text="Description of when this notification is sent"
    )
    
    # Template
    title_template = models.CharField(
        max_length=200,
        blank=True,
        help_text="Template for notification title with variables"
    )
    
    message_template = models.TextField(
        blank=True,
        help_text="Template for notification message with variables"
    )
    
    # Default settings
    default_email = models.BooleanField(
        default=True,
        help_text="Send email by default"
    )
    default_push = models.BooleanField(
        default=True,
        help_text="Send push notification by default"
    )
    default_in_app = models.BooleanField(
        default=True,
        help_text="Show in-app notification by default"
    )
    
    # System settings
    is_system = models.BooleanField(
        default=False,
        help_text="System notification that cannot be disabled"
    )
    
    priority = models.CharField(
        max_length=20,
        choices=[
            ('low', 'Low'),
            ('normal', 'Normal'),
            ('high', 'High'),
            ('urgent', 'Urgent')
        ],
        default='normal'
    )
    
    class Meta:
        db_table = 'notification_types'
        ordering = ['category', 'display_name']
    
    def __str__(self):
        return f"{self.category.name} - {self.display_name}"


class Notification(TimeStampedModel):
    """Individual notifications sent to users"""
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    
    notification_type = models.ForeignKey(
        NotificationType,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    
    # Content
    title = models.CharField(max_length=200)
    message = models.TextField()
    
    # Related object (generic relation)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Type of related object"
    )
    object_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="ID of related object"
    )
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Action URL
    action_url = models.CharField(
        max_length=500,
        blank=True,
        help_text="URL to navigate to when notification is clicked"
    )
    
    # Delivery channels
    CHANNEL_CHOICES = [
        ('in_app', 'In-App'),
        ('email', 'Email'),
        ('push', 'Push Notification'),
        ('sms', 'SMS')
    ]
    channels = models.JSONField(
        default=list,
        help_text="List of channels this notification was sent through"
    )
    
    # Status
    is_read = models.BooleanField(
        default=False,
        db_index=True
    )
    read_at = models.DateTimeField(null=True, blank=True)
    
    is_archived = models.BooleanField(
        default=False,
        help_text="User has archived this notification"
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    
    # Delivery status
    email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    email_opened = models.BooleanField(default=False)
    email_opened_at = models.DateTimeField(null=True, blank=True)
    
    push_sent = models.BooleanField(default=False)
    push_sent_at = models.DateTimeField(null=True, blank=True)
    
    # Scheduling
    scheduled_for = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When notification should be sent (null = send immediately)"
    )
    
    # Metadata
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional data for the notification"
    )
    
    # Expiration
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When notification becomes irrelevant"
    )
    
    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['scheduled_for']),
            models.Index(fields=['notification_type', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username}: {self.title}"
    
    def mark_as_read(self):
        """Mark notification as read"""
        if not self.is_read:
            from django.utils import timezone
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])
    
    def archive(self):
        """Archive notification"""
        if not self.is_archived:
            from django.utils import timezone
            self.is_archived = True
            self.archived_at = timezone.now()
            self.save(update_fields=['is_archived', 'archived_at'])
    
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
        User,
        on_delete=models.CASCADE,
        related_name='notification_preferences'
    )
    
    notification_type = models.ForeignKey(
        NotificationType,
        on_delete=models.CASCADE,
        related_name='user_preferences'
    )
    
    # Channel preferences
    email_enabled = models.BooleanField(default=True)
    push_enabled = models.BooleanField(default=True)
    in_app_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=False)
    
    # Frequency
    FREQUENCY_CHOICES = [
        ('instant', 'Instant'),
        ('hourly', 'Hourly Digest'),
        ('daily', 'Daily Digest'),
        ('weekly', 'Weekly Digest'),
        ('never', 'Never')
    ]
    frequency = models.CharField(
        max_length=20,
        choices=FREQUENCY_CHOICES,
        default='instant'
    )
    
    # Quiet hours
    quiet_hours_enabled = models.BooleanField(
        default=False,
        help_text="Don't send notifications during quiet hours"
    )
    quiet_hours_start = models.TimeField(
        null=True,
        blank=True,
        help_text="Start of quiet hours"
    )
    quiet_hours_end = models.TimeField(
        null=True,
        blank=True,
        help_text="End of quiet hours"
    )
    
    class Meta:
        db_table = 'user_notification_preferences'
        unique_together = [['user', 'notification_type']]
        ordering = ['user', 'notification_type']
    
    def __str__(self):
        return f"{self.user.username} - {self.notification_type.display_name}"


class NotificationDigest(TimeStampedModel):
    """Track digest notifications that have been sent"""
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notification_digests'
    )
    
    DIGEST_TYPES = [
        ('hourly', 'Hourly'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly')
    ]
    digest_type = models.CharField(
        max_length=20,
        choices=DIGEST_TYPES
    )
    
    # Period covered
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    
    # Content
    notification_count = models.IntegerField(
        default=0,
        help_text="Number of notifications included"
    )
    
    # Status
    is_sent = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'notification_digests'
        ordering = ['-period_end']
        indexes = [
            models.Index(fields=['user', 'digest_type']),
            models.Index(fields=['is_sent', 'period_end']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.digest_type} digest ({self.period_start.date()})"


class NotificationTemplate(TimeStampedModel):
    """Email/push templates for notifications"""
    
    notification_type = models.ForeignKey(
        NotificationType,
        on_delete=models.CASCADE,
        related_name='templates'
    )
    
    TEMPLATE_TYPES = [
        ('email_subject', 'Email Subject'),
        ('email_html', 'Email HTML Body'),
        ('email_text', 'Email Text Body'),
        ('push_title', 'Push Notification Title'),
        ('push_body', 'Push Notification Body'),
        ('in_app', 'In-App Notification')
    ]
    template_type = models.CharField(
        max_length=20,
        choices=TEMPLATE_TYPES
    )
    
    content = models.TextField(
        help_text="Template content with variables like {{user_name}}, {{trip_title}}"
    )
    
    # Version control
    version = models.IntegerField(default=1)
    is_active = models.BooleanField(default=True)
    
    # Variables documentation
    available_variables = models.JSONField(
        default=list,
        blank=True,
        help_text="List of available template variables"
    )
    
    class Meta:
        db_table = 'notification_templates'
        unique_together = [['notification_type', 'template_type', 'version']]
        ordering = ['notification_type', 'template_type', '-version']
    
    def __str__(self):
        return f"{self.notification_type.display_name} - {self.template_type} (v{self.version})"


class PushDevice(TimeStampedModel):
    """User devices registered for push notifications"""
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='push_devices'
    )
    
    DEVICE_TYPES = [
        ('ios', 'iOS'),
        ('android', 'Android'),
        ('web', 'Web Browser')
    ]
    device_type = models.CharField(
        max_length=20,
        choices=DEVICE_TYPES
    )
    
    # Device identifiers
    device_token = models.CharField(
        max_length=500,
        unique=True,
        help_text="Push notification token"
    )
    
    device_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="User-friendly device name"
    )
    
    # Device info
    app_version = models.CharField(max_length=50, blank=True)
    os_version = models.CharField(max_length=50, blank=True)
    
    # Status
    is_active = models.BooleanField(
        default=True,
        help_text="Whether device should receive notifications"
    )
    
    last_used_at = models.DateTimeField(
        auto_now=True,
        help_text="Last time this device was used"
    )
    
    class Meta:
        db_table = 'push_devices'
        ordering = ['user', '-last_used_at']
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['device_token']),
        ]
    
    def __str__(self):
        device_name = self.device_name or f"{self.device_type} device"
        return f"{self.user.username}'s {device_name}"