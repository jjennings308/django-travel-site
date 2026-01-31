# approval_system/models.py
"""
Reusable approval/moderation system for any model in your Django project.

Usage:
    class YourModel(Approvable):
        # your fields
        pass
"""

from django.db import models
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from core.models import TimeStampedModel


class ApprovalStatus(models.TextChoices):
    """Status choices for approvable content"""
    DRAFT = 'draft', 'Draft'
    PENDING = 'pending', 'Pending Review'
    APPROVED = 'approved', 'Approved'
    REJECTED = 'rejected', 'Rejected'
    CHANGES_REQUESTED = 'changes_requested', 'Changes Requested'
    ARCHIVED = 'archived', 'Archived'


class ApprovalPriority(models.TextChoices):
    """Priority levels for review queue"""
    LOW = 'low', 'Low Priority'
    NORMAL = 'normal', 'Normal'
    HIGH = 'high', 'High Priority'
    URGENT = 'urgent', 'Urgent'


class Approvable(models.Model):
    """
    Abstract base model for any content that needs approval.
    
    Add this to any model that needs approval workflow:
        class MyModel(Approvable):
            # your fields
    """
    
    approval_status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.DRAFT,
        db_index=True,
        help_text='Current approval status'
    )
    
    # Submission tracking
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(app_label)s_%(class)s_submissions',
        help_text='User who submitted this content'
    )
    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When content was submitted for review'
    )
    
    # Review tracking
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(app_label)s_%(class)s_reviews',
        help_text='Staff member who reviewed this content'
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When content was reviewed'
    )
    
    # Priority for review queue
    approval_priority = models.CharField(
        max_length=10,
        choices=ApprovalPriority.choices,
        default=ApprovalPriority.NORMAL,
        help_text='Priority in review queue'
    )
    
    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=['approval_status', '-submitted_at']),
            models.Index(fields=['approval_priority', '-submitted_at']),
        ]
    
    def is_public(self):
        """Check if content is visible to public"""
        return self.approval_status == ApprovalStatus.APPROVED
    
    def is_pending(self):
        """Check if content is awaiting review"""
        return self.approval_status == ApprovalStatus.PENDING
    
    def is_draft(self):
        """Check if content is in draft state"""
        return self.approval_status == ApprovalStatus.DRAFT
    
    def submit_for_review(self, user=None):
        """Submit content for review"""
        self.approval_status = ApprovalStatus.PENDING
        self.submitted_at = timezone.now()
        if user:
            self.submitted_by = user
        self.save()
        
        # Create approval log entry
        ApprovalLog.objects.create(
            content_object=self,
            action='submitted',
            performed_by=user,
            new_status=ApprovalStatus.PENDING,
            notes='Submitted for review'
        )
    
    def approve(self, reviewer, notes=''):
        """Approve this content"""
        old_status = self.approval_status
        self.approval_status = ApprovalStatus.APPROVED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.save()
        
        # Create approval log entry
        ApprovalLog.objects.create(
            content_object=self,
            action='approved',
            performed_by=reviewer,
            old_status=old_status,
            new_status=ApprovalStatus.APPROVED,
            notes=notes
        )
        
        # Send notification to submitter
        self._send_approval_notification('approved', notes)
    
    def reject(self, reviewer, notes=''):
        """Reject this content"""
        old_status = self.approval_status
        self.approval_status = ApprovalStatus.REJECTED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.save()
        
        # Create approval log entry
        ApprovalLog.objects.create(
            content_object=self,
            action='rejected',
            performed_by=reviewer,
            old_status=old_status,
            new_status=ApprovalStatus.REJECTED,
            notes=notes
        )
        
        # Send notification to submitter
        self._send_approval_notification('rejected', notes)
    
    def request_changes(self, reviewer, notes=''):
        """Request changes to this content"""
        old_status = self.approval_status
        self.approval_status = ApprovalStatus.CHANGES_REQUESTED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.save()
        
        # Create approval log entry
        ApprovalLog.objects.create(
            content_object=self,
            action='changes_requested',
            performed_by=reviewer,
            old_status=old_status,
            new_status=ApprovalStatus.CHANGES_REQUESTED,
            notes=notes
        )
        
        # Send notification to submitter
        self._send_approval_notification('changes_requested', notes)
    
    def archive(self, user, notes=''):
        """Archive this content"""
        old_status = self.approval_status
        self.approval_status = ApprovalStatus.ARCHIVED
        self.save()
        
        # Create approval log entry
        ApprovalLog.objects.create(
            content_object=self,
            action='archived',
            performed_by=user,
            old_status=old_status,
            new_status=ApprovalStatus.ARCHIVED,
            notes=notes
        )
    
    def _send_approval_notification(self, action, notes=''):
        """Send notification about approval action"""
        # This can be implemented to send emails, in-app notifications, etc.
        # For now, just create a notification record
        if self.submitted_by:
            from notifications.models import Notification  # Assuming you have notifications app
            # Notification.objects.create(...)
            pass
    
    def get_approval_history(self):
        """Get all approval log entries for this object"""
        content_type = ContentType.objects.get_for_model(self.__class__)
        return ApprovalLog.objects.filter(
            content_type=content_type,
            object_id=self.pk
        ).order_by('-created_at')


class ApprovalLog(TimeStampedModel):
    """
    Audit trail for all approval actions.
    Tracks every status change with who, when, and why.
    """
    
    # Generic relation to any approvable model
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE
    )
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Action details
    ACTION_CHOICES = [
        ('submitted', 'Submitted for Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('changes_requested', 'Changes Requested'),
        ('archived', 'Archived'),
        ('edited', 'Edited'),
        ('priority_changed', 'Priority Changed'),
    ]
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    
    # Who performed the action
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='approval_actions'
    )
    
    # Status transition
    old_status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        blank=True,
        null=True
    )
    new_status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        blank=True,
        null=True
    )
    
    # Additional context
    notes = models.TextField(blank=True, help_text='Reason or comments')
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text='Additional data (changed fields, etc.)'
    )
    
    # IP tracking (optional, for security)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    class Meta:
        db_table = 'approval_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['performed_by', '-created_at']),
            models.Index(fields=['action', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.get_action_display()} by {self.performed_by} on {self.created_at}"


class ApprovalRule(TimeStampedModel):
    """
    Configurable rules for auto-approval or routing.
    E.g., "Auto-approve if user has >10 approved items"
    """
    
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # What content type does this apply to?
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        help_text='Type of content this rule applies to'
    )
    
    # Rule configuration
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(
        default=0,
        help_text='Higher priority rules are evaluated first'
    )
    
    # Auto-approval settings
    auto_approve = models.BooleanField(
        default=False,
        help_text='Automatically approve if conditions met'
    )
    auto_reject = models.BooleanField(
        default=False,
        help_text='Automatically reject if conditions met'
    )
    
    # Routing settings
    assign_to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_approvals',
        help_text='Assign matching items to this reviewer'
    )
    
    # Conditions (stored as JSON)
    conditions = models.JSONField(
        default=dict,
        help_text='Conditions that must be met for this rule to apply'
    )
    
    # Example conditions:
    # {
    #     "user_approved_count_gte": 10,  # User has 10+ approved items
    #     "user_groups": ["trusted_contributors"],  # User in specific group
    #     "field_checks": {
    #         "has_image": True,  # Item has an image
    #         "word_count_gte": 100  # Description >= 100 words
    #     }
    # }
    
    class Meta:
        db_table = 'approval_rules'
        ordering = ['-priority', 'name']
    
    def __str__(self):
        return self.name
    
    def evaluate(self, obj):
        """
        Evaluate if this rule applies to the given object.
        Returns True if all conditions are met.
        """
        # This would contain logic to check conditions
        # For now, just a placeholder
        return False


class ApprovalQueue(models.Model):
    """
    Custom review queues for organizing pending items.
    E.g., "Urgent Review", "New Contributors", "High Value Content"
    """
    
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    slug = models.SlugField(unique=True)
    
    # Assignees
    reviewers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='approval_queues',
        blank=True,
        help_text='Staff members assigned to this queue'
    )
    
    # Filters for this queue
    content_types = models.ManyToManyField(
        ContentType,
        help_text='Types of content in this queue'
    )
    
    status_filter = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
        help_text='Show items with this status'
    )
    
    priority_filter = models.CharField(
        max_length=10,
        choices=ApprovalPriority.choices,
        blank=True,
        help_text='Show items with this priority (blank = all)'
    )
    
    # Display settings
    color = models.CharField(
        max_length=7,
        default='#007bff',
        help_text='Color for queue badge (hex)'
    )
    icon = models.CharField(
        max_length=50,
        blank=True,
        help_text='Icon class or emoji'
    )
    
    # Stats
    is_active = models.BooleanField(default=True)
    display_order = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'approval_queues'
        ordering = ['display_order', 'name']
    
    def __str__(self):
        return self.name
    
    def get_pending_count(self):
        """Get count of items in this queue"""
        count = 0
        for content_type in self.content_types.all():
            model = content_type.model_class()
            if model:
                queryset = model.objects.filter(approval_status=self.status_filter)
                if self.priority_filter:
                    queryset = queryset.filter(approval_priority=self.priority_filter)
                count += queryset.count()
        return count


class ApprovalSettings(models.Model):
    """
    Global settings for the approval system.
    Singleton model (only one instance should exist).
    """
    
    # Notification settings
    notify_on_submission = models.BooleanField(
        default=True,
        help_text='Notify reviewers when new items are submitted'
    )
    notify_on_approval = models.BooleanField(
        default=True,
        help_text='Notify submitters when items are approved'
    )
    notify_on_rejection = models.BooleanField(
        default=True,
        help_text='Notify submitters when items are rejected'
    )
    
    # Auto-archive settings
    auto_archive_rejected_days = models.IntegerField(
        default=30,
        help_text='Auto-archive rejected items after X days (0 = never)'
    )
    
    # Review SLA
    review_sla_hours = models.IntegerField(
        default=48,
        help_text='Expected review time in hours (for metrics)'
    )
    
    # Dashboard settings
    items_per_page = models.IntegerField(default=25)
    show_archived_in_search = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'approval_settings'
        verbose_name = 'Approval Settings'
        verbose_name_plural = 'Approval Settings'
    
    def save(self, *args, **kwargs):
        # Ensure only one instance exists
        self.pk = 1
        super().save(*args, **kwargs)
    
    @classmethod
    def get_settings(cls):
        """Get or create the settings instance"""
        obj, created = cls.objects.get_or_create(pk=1)
        return obj
