# admin_tools/models.py
from django.db import models
from core.models import TimeStampedModel
from accounts.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType


class ModerationQueue(TimeStampedModel):
    """Queue for content that needs moderation"""
    
    # Content being moderated (generic relation)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        help_text="Type of content (Review, Media, etc.)"
    )
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Submitter
    submitted_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='submitted_for_moderation'
    )
    
    # Reason for moderation
    REASON_CHOICES = [
        ('new_content', 'New Content Review'),
        ('user_report', 'User Report'),
        ('auto_flag', 'Automatic Flag'),
        ('policy_violation', 'Policy Violation'),
        ('spam_detection', 'Spam Detection'),
        ('quality_check', 'Quality Check')
    ]
    reason = models.CharField(
        max_length=20,
        choices=REASON_CHOICES
    )
    
    reason_details = models.TextField(
        blank=True,
        help_text="Additional details about why this needs moderation"
    )
    
    # Priority
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('urgent', 'Urgent')
    ]
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default='normal',
        db_index=True
    )
    
    # Status
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('in_review', 'In Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('escalated', 'Escalated')
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )
    
    # Review
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='moderation_reviews'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    
    # Action taken
    action_taken = models.CharField(
        max_length=100,
        blank=True,
        help_text="Action taken by moderator"
    )
    
    # Escalation
    escalated_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='escalated_moderations'
    )
    escalation_reason = models.TextField(blank=True)
    
    class Meta:
        db_table = 'moderation_queue'
        ordering = ['-priority', '-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['priority', 'status']),
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['reviewed_by']),
        ]
    
    def __str__(self):
        return f"Moderation: {self.content_type.model} #{self.object_id} ({self.status})"
    
    def approve(self, moderator, notes=''):
        """Approve content"""
        from django.utils import timezone
        self.status = 'approved'
        self.reviewed_by = moderator
        self.reviewed_at = timezone.now()
        self.review_notes = notes
        self.save()
    
    def reject(self, moderator, notes='', action=''):
        """Reject content"""
        from django.utils import timezone
        self.status = 'rejected'
        self.reviewed_by = moderator
        self.reviewed_at = timezone.now()
        self.review_notes = notes
        self.action_taken = action
        self.save()
    
    def escalate(self, moderator, escalate_to, reason=''):
        """Escalate to senior moderator"""
        from django.utils import timezone
        self.status = 'escalated'
        self.reviewed_by = moderator
        self.reviewed_at = timezone.now()
        self.escalated_to = escalate_to
        self.escalation_reason = reason
        self.save()


class ReportedContent(TimeStampedModel):
    """User reports of inappropriate content"""
    
    # Reporter
    reporter = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='content_reports'
    )
    
    # Reported content (generic relation)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE
    )
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Report details
    REPORT_REASONS = [
        ('spam', 'Spam'),
        ('harassment', 'Harassment'),
        ('hate_speech', 'Hate Speech'),
        ('violence', 'Violence'),
        ('nudity', 'Nudity/Sexual Content'),
        ('false_info', 'False Information'),
        ('copyright', 'Copyright Violation'),
        ('personal_info', 'Sharing Personal Information'),
        ('scam', 'Scam/Fraud'),
        ('other', 'Other')
    ]
    reason = models.CharField(
        max_length=20,
        choices=REPORT_REASONS
    )
    
    description = models.TextField(
        help_text="Detailed description of the issue"
    )
    
    # Evidence
    evidence_urls = models.JSONField(
        default=list,
        blank=True,
        help_text="URLs to screenshots or evidence"
    )
    
    # Status
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('investigating', 'Under Investigation'),
        ('resolved', 'Resolved'),
        ('dismissed', 'Dismissed'),
        ('escalated', 'Escalated')
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )
    
    # Review
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_reports'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)
    
    # Action taken
    action_taken = models.CharField(
        max_length=200,
        blank=True,
        help_text="What action was taken"
    )
    
    # Follow-up
    requires_followup = models.BooleanField(default=False)
    followup_notes = models.TextField(blank=True)
    
    class Meta:
        db_table = 'reported_content'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['reporter', '-created_at']),
            models.Index(fields=['content_type', 'object_id']),
        ]
    
    def __str__(self):
        return f"Report by {self.reporter.username}: {self.reason}"


class UserActivityLog(TimeStampedModel):
    """Log of user activities for admin monitoring"""
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='activity_logs'
    )
    
    ACTION_TYPES = [
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('view', 'View'),
        ('download', 'Download'),
        ('share', 'Share'),
        ('report', 'Report'),
        ('review', 'Review'),
        ('booking', 'Booking'),
        ('payment', 'Payment'),
        ('other', 'Other')
    ]
    action_type = models.CharField(
        max_length=20,
        choices=ACTION_TYPES,
        db_index=True
    )
    
    action_description = models.CharField(
        max_length=300,
        help_text="Brief description of action"
    )
    
    # Related object (optional)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Metadata
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    device_type = models.CharField(max_length=50, blank=True)
    
    # Additional data
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional context data"
    )
    
    class Meta:
        db_table = 'user_activity_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['action_type', '-created_at']),
            models.Index(fields=['-created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username}: {self.action_type} - {self.action_description}"


class SystemMetrics(TimeStampedModel):
    """System-wide metrics and statistics"""
    
    # Time period
    date = models.DateField(unique=True, db_index=True)
    
    # User metrics
    total_users = models.IntegerField(default=0)
    new_users_today = models.IntegerField(default=0)
    active_users_today = models.IntegerField(default=0)
    premium_users = models.IntegerField(default=0)
    
    # Content metrics
    total_trips = models.IntegerField(default=0)
    trips_created_today = models.IntegerField(default=0)
    total_bucket_list_items = models.IntegerField(default=0)
    bucket_list_items_added_today = models.IntegerField(default=0)
    total_reviews = models.IntegerField(default=0)
    reviews_created_today = models.IntegerField(default=0)
    
    # Engagement metrics
    total_page_views = models.BigIntegerField(default=0)
    total_sessions = models.IntegerField(default=0)
    avg_session_duration = models.IntegerField(
        default=0,
        help_text="Average session duration in seconds"
    )
    
    # Activity metrics
    total_activities = models.IntegerField(default=0)
    total_events = models.IntegerField(default=0)
    total_locations = models.IntegerField(default=0)
    total_vendors = models.IntegerField(default=0)
    
    # Moderation metrics
    pending_moderation_count = models.IntegerField(default=0)
    reports_resolved_today = models.IntegerField(default=0)
    
    # System health
    avg_response_time = models.IntegerField(
        default=0,
        help_text="Average API response time in milliseconds"
    )
    error_count = models.IntegerField(
        default=0,
        help_text="Number of errors today"
    )
    
    # Revenue (if applicable)
    revenue_today = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.0
    )
    
    # Additional metrics
    custom_metrics = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional custom metrics"
    )
    
    class Meta:
        db_table = 'system_metrics'
        verbose_name_plural = 'System Metrics'
        ordering = ['-date']
    
    def __str__(self):
        return f"Metrics for {self.date}"


class ModeratorNote(TimeStampedModel):
    """Internal notes for moderators"""
    
    # Author
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='moderator_notes'
    )
    
    # Subject (what the note is about)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Note content
    note = models.TextField()
    
    # Visibility
    is_internal = models.BooleanField(
        default=True,
        help_text="Only visible to moderators"
    )
    
    # Importance
    is_pinned = models.BooleanField(
        default=False,
        help_text="Pin this note for visibility"
    )
    
    class Meta:
        db_table = 'moderator_notes'
        ordering = ['-is_pinned', '-created_at']
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['-created_at']),
        ]
    
    def __str__(self):
        return f"Note by {self.author.username} on {self.created_at.date()}"


class AdminAction(TimeStampedModel):
    """Log of admin actions for audit trail"""
    
    admin = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='admin_actions'
    )
    
    ACTION_TYPES = [
        ('user_ban', 'User Ban'),
        ('user_unban', 'User Unban'),
        ('content_remove', 'Content Remove'),
        ('content_restore', 'Content Restore'),
        ('feature_flag', 'Feature Flag Change'),
        ('config_change', 'Configuration Change'),
        ('data_export', 'Data Export'),
        ('bulk_action', 'Bulk Action'),
        ('other', 'Other')
    ]
    action_type = models.CharField(
        max_length=20,
        choices=ACTION_TYPES,
        db_index=True
    )
    
    description = models.TextField(
        help_text="Description of action taken"
    )
    
    # Affected object
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Details
    before_state = models.JSONField(
        default=dict,
        blank=True,
        help_text="State before action"
    )
    after_state = models.JSONField(
        default=dict,
        blank=True,
        help_text="State after action"
    )
    
    # Context
    reason = models.TextField(
        blank=True,
        help_text="Reason for taking this action"
    )
    
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    class Meta:
        db_table = 'admin_actions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['admin', '-created_at']),
            models.Index(fields=['action_type', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.admin.username}: {self.action_type} at {self.created_at}"