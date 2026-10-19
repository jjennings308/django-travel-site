# admin_tools/models.py
from django.db import models
from apps.core.models import TimeStampedModel
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType


class ReportedContent(TimeStampedModel):
    """User reports of inappropriate content"""
    
    # Reporter
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
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
        settings.AUTH_USER_MODEL,
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


