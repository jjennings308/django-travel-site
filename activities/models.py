# activities/models.py
from django.db import models
from django.conf import settings
from core.models import TimeStampedModel, SlugMixin, FeaturedContentMixin
from django.core.validators import MinValueValidator, MaxValueValidator
from approval_system.models import Approvable, ApprovalStatus


class ActivityCategory(TimeStampedModel, SlugMixin):
    """Top-level activity categories"""
    
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="E.g., Adventure, Cultural, Food & Drink"
    )
    description = models.TextField(blank=True)
    icon = models.CharField(
        max_length=50,
        blank=True,
        help_text="Icon name or emoji"
    )
    
    # Display
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    # Allow user submissions?
    allow_user_submissions = models.BooleanField(
        default=True,
        help_text="Allow regular users to submit activities in this category"
    )
    
    class Meta:
        db_table = 'activities_categories'
        verbose_name_plural = 'Activity Categories'
        ordering = ['display_order', 'name']
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.slug:
            from core.utils import generate_unique_slug
            self.slug = generate_unique_slug(ActivityCategory, self.name, self.id)
        super().save(*args, **kwargs)


class Activity(TimeStampedModel, SlugMixin, FeaturedContentMixin, Approvable):
    """
    Activities that users can do - can be user-submitted or staff-created.
    
    User Flow:
    - Regular users create activities as DRAFT or PRIVATE
    - If they want it PUBLIC, they submit for approval (PENDING)
    - Staff reviews and approves/rejects
    - Staff can create activities directly as APPROVED
    
    Visibility:
    - PRIVATE: Only visible to creator
    - DRAFT: Only visible to creator (not submitted yet)
    - PENDING: Visible to staff for review
    - APPROVED: Visible to everyone
    - REJECTED: Only visible to creator with rejection reason
    """
    
    # Core info
    category = models.ForeignKey(
        ActivityCategory,
        on_delete=models.PROTECT,
        related_name='activities'
    )
    
    name = models.CharField(
        max_length=200,
        help_text="E.g., 'See Kenny Chesney concert' or 'Go skydiving' or 'Visit a museum'"
    )
    description = models.TextField(
        help_text="Detailed description of the activity"
    )
    short_description = models.CharField(
        max_length=300,
        blank=True,
        help_text="Brief description for cards/lists"
    )
    
    # Creator and visibility
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_activities',
        help_text="User who created this activity",
    )    

    VISIBILITY_CHOICES = [
        ('private', 'Private - Only I can see'),
        ('public', 'Public - Everyone can see (requires approval)'),
    ]
    visibility = models.CharField(
        max_length=20,
        choices=VISIBILITY_CHOICES,
        default='private',
        help_text="Who can see this activity"
    )
    
    # If user wants this to be public, it goes through approval
    # approval_status (from Approvable mixin):
    #   - draft: User hasn't submitted for public yet
    #   - pending: Submitted for approval
    #   - approved: Approved and public
    #   - rejected: Rejected, visible only to creator
    
    # Source tracking
    SOURCE_CHOICES = [
        ('user', 'User Created'),
        ('staff', 'Staff Created'),
        ('import', 'Imported'),
    ]
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default='user',
        help_text="How this activity was created"
    )
    
    # Specificity level - how detailed is this activity?
    SPECIFICITY_CHOICES = [
        ('general', 'General - e.g., "Go to a concert"'),
        ('specific', 'Specific - e.g., "See Kenny Chesney at Vegas Sphere"'),
        ('very_specific', 'Very Specific - includes dates/times'),
    ]
    specificity_level = models.CharField(
        max_length=20,
        choices=SPECIFICITY_CHOICES,
        default='general',
        help_text="How specific is this activity description?"
    )
    
    # Optional: Suggested details that could turn this into an event
    suggested_location = models.CharField(
        max_length=200,
        blank=True,
        help_text="Suggested location (e.g., 'Vegas Sphere')"
    )
    suggested_timeframe = models.CharField(
        max_length=200,
        blank=True,
        help_text="Suggested timeframe (e.g., 'Summer 2026')"
    )
    suggested_date_range_start = models.DateField(
        null=True,
        blank=True,
        help_text="Suggested start of date range"
    )
    suggested_date_range_end = models.DateField(
        null=True,
        blank=True,
        help_text="Suggested end of date range"
    )
    
    # Difficulty and requirements
    SKILL_LEVELS = [
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
        ('expert', 'Expert'),
        ('any', 'Any Level'),
    ]
    skill_level = models.CharField(
        max_length=20,
        choices=SKILL_LEVELS,
        default='any'
    )
    
    # Physical requirements
    fitness_required = models.IntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="1=Low, 5=Very High physical fitness required"
    )
    
    age_minimum = models.IntegerField(
        null=True,
        blank=True,
        help_text="Minimum age to participate"
    )
    age_maximum = models.IntegerField(
        null=True,
        blank=True,
        help_text="Maximum age to participate"
    )
    
    # Time and cost
    typical_duration = models.IntegerField(
        null=True,
        blank=True,
        help_text="Typical duration in minutes"
    )
    
    DURATION_CATEGORIES = [
        ('quick', 'Quick (< 1 hour)'),
        ('short', 'Short (1-3 hours)'),
        ('half_day', 'Half Day (3-5 hours)'),
        ('full_day', 'Full Day (5-8 hours)'),
        ('multi_day', 'Multi-Day'),
        ('varies', 'Varies'),
    ]
    duration_category = models.CharField(
        max_length=20,
        choices=DURATION_CATEGORIES,
        default='varies'
    )
    
    estimated_cost_min = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Minimum estimated cost in USD"
    )
    estimated_cost_max = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Maximum estimated cost in USD"
    )
    
    COST_LEVELS = [
        ('free', 'Free'),
        ('budget', 'Budget ($)'),
        ('moderate', 'Moderate ($$)'),
        ('expensive', 'Expensive ($$$)'),
        ('luxury', 'Luxury ($$$$)'),
        ('varies', 'Varies'),
    ]
    cost_level = models.CharField(
        max_length=20,
        choices=COST_LEVELS,
        default='varies'
    )
    
    # Activity characteristics
    ACTIVITY_STYLES = [
        ('solo', 'Best Solo'),
        ('couple', 'Romantic/Couples'),
        ('family', 'Family Friendly'),
        ('group', 'Group Activity'),
        ('any', 'Any Group Size')
    ]
    best_for = models.CharField(
        max_length=20,
        choices=ACTIVITY_STYLES,
        default='any'
    )
    
    # Season/weather
    SEASONS = [
        ('spring', 'Spring'),
        ('summer', 'Summer'),
        ('fall', 'Fall'),
        ('winter', 'Winter'),
        ('year_round', 'Year Round')
    ]
    best_season = models.JSONField(
        default=list,
        blank=True,
        help_text="List of best seasons for this activity"
    )
    
    indoor_outdoor = models.CharField(
        max_length=20,
        choices=[
            ('indoor', 'Indoor'),
            ('outdoor', 'Outdoor'),
            ('both', 'Both'),
            ('either', 'Either/Not Specified'),
        ],
        default='either'
    )
    
    # Requirements and resources
    equipment_needed = models.TextField(
        blank=True,
        help_text="List of equipment/gear needed"
    )
    booking_required = models.BooleanField(
        default=False,
        help_text="Whether advance booking is typically required"
    )
    guide_required = models.BooleanField(
        default=False,
        help_text="Whether a guide is typically required"
    )
    
    # Accessibility
    wheelchair_accessible = models.BooleanField(
        default=False,
        null=True,
        blank=True
    )
    suitable_for_children = models.BooleanField(
        default=True,
        null=True,
        blank=True
    )
    
    # Safety
    risk_level = models.CharField(
        max_length=20,
        choices=[
            ('low', 'Low Risk'),
            ('moderate', 'Moderate Risk'),
            ('high', 'High Risk'),
            ('extreme', 'Extreme Risk')
        ],
        default='low',
        help_text="Risk level of this activity"  # Optional: add help text
    )
    
    safety_notes = models.TextField(
        blank=True,
        help_text="Important safety information"
    )
    
    # Stats and engagement
    popularity_score = models.IntegerField(
        default=0,
        help_text="Calculated popularity score"
    )
    bucket_list_count = models.IntegerField(
        default=0,
        help_text="How many times added to bucket lists"
    )
    completed_count = models.IntegerField(
        default=0,
        help_text="How many times marked as completed"
    )
    event_count = models.IntegerField(
        default=0,
        help_text="How many events created from this activity"
    )
    average_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(5)]
    )
    review_count = models.IntegerField(default=0)
    
    # For rejected items, why?
    rejection_notes = models.TextField(
        blank=True,
        help_text="Staff notes on why this was rejected (visible to creator)"
    )
    
    class Meta:
        db_table = 'activities'
        verbose_name_plural = 'Activities'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['category', 'approval_status']),
            models.Index(fields=['created_by', 'visibility']),
            models.Index(fields=['visibility', 'approval_status']),
            models.Index(fields=['-popularity_score']),
            models.Index(fields=['source']),
        ]
        permissions = [
            ('can_approve_activities', 'Can approve user-submitted activities'),
            ('can_bypass_approval', 'Can create pre-approved activities'),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.category.name}) - {self.get_visibility_display()}"
    
    def save(self, *args, **kwargs):
        # Auto-generate slug if needed
        if not self.slug:
            from core.utils import generate_unique_slug
            slug_parts = [self.name]
            if self.created_by:
                slug_parts.append(str(self.created_by.id))
            slug_base = '-'.join(slug_parts)
            self.slug = generate_unique_slug(Activity, slug_base, self.id)
        
        # Auto-set short description if empty
        if not self.short_description and self.description:
            self.short_description = self.description[:297] + '...' if len(self.description) > 300 else self.description
        
        # If staff is creating and source is staff, auto-approve
        if self.source == 'staff' and not self.pk:
            # New staff-created activity
            self.approval_status = ApprovalStatus.APPROVED
        
        super().save(*args, **kwargs)
    
    # Visibility helpers
    def is_visible_to(self, user):
        """Check if this activity is visible to a given user"""
        # Creator can always see their own activities
        if user and user.is_authenticated and user == self.created_by:
            return True
        
        # Staff can see everything
        if user and user.is_authenticated and user.is_staff:
            return True
        
        # Public approved activities visible to all
        if self.visibility == 'public' and self.approval_status == ApprovalStatus.APPROVED:
            return True
        
        # Everything else is not visible
        return False
    
    def can_edit(self, user):
        """Check if user can edit this activity"""
        if not user or not user.is_authenticated:
            return False
        
        # Creator can edit if not approved yet
        if user == self.created_by and self.approval_status != ApprovalStatus.APPROVED:
            return True
        
        # Staff can always edit
        if user.is_staff:
            return True
        
        return False
    
    def can_delete(self, user):
        """Check if user can delete this activity"""
        if not user or not user.is_authenticated:
            return False
        
        # Creator can delete their own if not approved
        if user == self.created_by and self.approval_status != ApprovalStatus.APPROVED:
            return True
        
        # Staff can always delete
        if user.is_staff:
            return True
        
        return False
    
    def submit_for_public(self, user=None):
        """
        Submit this activity to be made public.
        Changes visibility to public and approval_status to pending.
        """
        if self.visibility != 'public':
            self.visibility = 'public'
        
        # Use the submit_for_review method from Approvable
        self.submit_for_review(user)
    
    def make_private(self):
        """Change activity back to private"""
        self.visibility = 'private'
        self.approval_status = ApprovalStatus.DRAFT
        self.save()
    
    @classmethod
    def get_public_activities(cls):
        """Get all approved public activities"""
        return cls.objects.filter(
            visibility='public',
            approval_status=ApprovalStatus.APPROVED
        )
    
    @classmethod
    def get_user_activities(cls, user):
        """Get all activities created by a user"""
        return cls.objects.filter(created_by=user)
    
    @classmethod
    def get_pending_approval(cls):
        """Get all activities pending approval"""
        return cls.objects.filter(
            visibility='public',
            approval_status=ApprovalStatus.PENDING
        ).order_by('-submitted_at')


class ActivityTag(TimeStampedModel, SlugMixin):
    """Tags for filtering and categorizing activities"""
    
    name = models.CharField(
        max_length=50,
        unique=True,
        help_text="E.g., outdoor, adrenaline, cultural, romantic"
    )
    description = models.CharField(max_length=200, blank=True)
    
    # Many-to-many with Activity
    activities = models.ManyToManyField(
        Activity,
        related_name='tags',
        blank=True
    )
    
    usage_count = models.IntegerField(
        default=0,
        help_text="How many activities use this tag"
    )
    
    # Can users add this tag or is it staff-only?
    user_can_add = models.BooleanField(
        default=True,
        help_text="Whether regular users can add this tag to activities"
    )
    
    class Meta:
        db_table = 'activity_tags'
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.slug:
            from core.utils import generate_unique_slug
            self.slug = generate_unique_slug(ActivityTag, self.name, self.id)
        super().save(*args, **kwargs)


class UserActivityBookmark(TimeStampedModel):
    """
    Users can bookmark activities (public or their own private ones)
    to use later when creating events or bucket list items
    """
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='activity_bookmarks'
    )
    activity = models.ForeignKey(
        Activity,
        on_delete=models.CASCADE,
        related_name='bookmarks'
    )
    
    notes = models.TextField(
        blank=True,
        help_text="Personal notes about this activity"
    )
    
    # User might want to track their interest level
    interest_level = models.IntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="1=Mild Interest, 5=Really Want To Do"
    )
    
    class Meta:
        db_table = 'user_activity_bookmarks'
        unique_together = [['user', 'activity']]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} bookmarked {self.activity.name}"
