# reviews/models.py
from django.db import models
from core.models import TimeStampedModel
from accounts.models import User
from vendors.models import Vendor
from activities.models import Activity
from events.models import Event
from locations.models import City
from trips.models import Trip
from django.core.validators import MinValueValidator, MaxValueValidator


class Review(TimeStampedModel):
    """User reviews for various content types"""
    
    # Reviewer
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    
    # What's being reviewed (only ONE should be set)
    REVIEW_TYPES = [
        ('vendor', 'Vendor'),
        ('activity', 'Activity'),
        ('event', 'Event'),
        ('location', 'Location'),
        ('trip', 'Trip'),
        ('site', 'Website Feedback')
    ]
    review_type = models.CharField(
        max_length=20,
        choices=REVIEW_TYPES,
        db_index=True
    )
    
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='reviews'
    )
    
    activity = models.ForeignKey(
        Activity,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='reviews'
    )
    
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='reviews'
    )
    
    location = models.ForeignKey(
        City,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='reviews'
    )
    
    trip = models.ForeignKey(
        Trip,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='reviews',
        help_text="For reviewing someone else's public trip itinerary"
    )
    
    # Rating (1-5 stars)
    rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Rating from 1 to 5"
    )
    
    # Review content
    title = models.CharField(
        max_length=200,
        blank=True,
        help_text="Review title/headline"
    )
    
    comment = models.TextField(
        help_text="Detailed review"
    )
    
    # Additional ratings (optional, specific to review type)
    # For vendors (hotels, restaurants)
    value_rating = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Value for money"
    )
    service_rating = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Service quality"
    )
    cleanliness_rating = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Cleanliness (for accommodations)"
    )
    
    # For activities/events
    difficulty_rating = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Difficulty level (1=easy, 5=very hard)"
    )
    
    # Context
    visit_date = models.DateField(
        null=True,
        blank=True,
        help_text="When did you visit/experience this?"
    )
    
    travel_type = models.CharField(
        max_length=20,
        choices=[
            ('solo', 'Solo'),
            ('couple', 'Couple'),
            ('family', 'Family'),
            ('friends', 'Friends'),
            ('business', 'Business')
        ],
        blank=True
    )
    
    # Pros and cons
    pros = models.TextField(
        blank=True,
        help_text="What you liked"
    )
    
    cons = models.TextField(
        blank=True,
        help_text="What could be improved"
    )
    
    # Tips
    tips = models.TextField(
        blank=True,
        help_text="Tips for future visitors"
    )
    
    # Site feedback specific fields
    site_feedback_category = models.CharField(
        max_length=20,
        choices=[
            ('ui_ux', 'User Interface/Design'),
            ('feature', 'Feature Request'),
            ('bug', 'Bug Report'),
            ('performance', 'Speed/Performance'),
            ('general', 'General Feedback')
        ],
        blank=True
    )
    
    # Verification
    is_verified_visit = models.BooleanField(
        default=False,
        help_text="User verified they actually visited/experienced this"
    )
    
    # Moderation
    is_approved = models.BooleanField(
        default=True,
        help_text="Approved by moderators"
    )
    
    is_featured = models.BooleanField(
        default=False,
        help_text="Featured review (highlighted)"
    )
    
    is_flagged = models.BooleanField(default=False)
    flagged_reason = models.TextField(blank=True)
    
    # Engagement
    helpful_count = models.IntegerField(
        default=0,
        help_text="Number of users who found this helpful"
    )
    
    report_count = models.IntegerField(
        default=0,
        help_text="Number of times reported"
    )
    
    # Response from business/admin
    has_response = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'reviews'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['review_type', '-created_at']),
            models.Index(fields=['rating', '-created_at']),
            models.Index(fields=['is_approved', '-created_at']),
        ]
        # Ensure user can only review each item once
        unique_together = [
            ['user', 'vendor'],
            ['user', 'activity'],
            ['user', 'event'],
            ['user', 'location'],
            ['user', 'trip'],
        ]
    
    def __str__(self):
        target = self.get_review_target_name()
        return f"{self.user.username}'s review of {target} ({self.rating}★)"
    
    def get_review_target_name(self):
        """Get the name of what's being reviewed"""
        if self.vendor:
            return self.vendor.name
        elif self.activity:
            return self.activity.name
        elif self.event:
            return self.event.name
        elif self.location:
            return self.location.name
        elif self.trip:
            return self.trip.title
        elif self.review_type == 'site':
            return "Website"
        return "Unknown"
    
    @property
    def average_detailed_rating(self):
        """Calculate average of detailed ratings if available"""
        ratings = [
            r for r in [
                self.value_rating,
                self.service_rating,
                self.cleanliness_rating
            ] if r is not None
        ]
        if ratings:
            return sum(ratings) / len(ratings)
        return None
    
    def clean(self):
        """Validate that exactly one content reference is set"""
        from django.core.exceptions import ValidationError
        
        if self.review_type == 'site':
            # Site feedback doesn't need any FK
            return
        
        references = sum([
            bool(self.vendor),
            bool(self.activity),
            bool(self.event),
            bool(self.location),
            bool(self.trip)
        ])
        
        if references == 0:
            raise ValidationError('Must specify what is being reviewed')
        elif references > 1:
            raise ValidationError('Can only review one item at a time')


class ReviewResponse(TimeStampedModel):
    """Responses to reviews (from business owners or admins)"""
    
    review = models.OneToOneField(
        Review,
        on_delete=models.CASCADE,
        related_name='response'
    )
    
    responder = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='review_responses'
    )
    
    RESPONDER_TYPES = [
        ('owner', 'Business Owner'),
        ('manager', 'Manager'),
        ('admin', 'Site Admin'),
        ('staff', 'Staff Member')
    ]
    responder_type = models.CharField(
        max_length=20,
        choices=RESPONDER_TYPES,
        default='owner'
    )
    
    response_text = models.TextField()
    
    is_approved = models.BooleanField(
        default=True,
        help_text="Response approved by moderators"
    )
    
    class Meta:
        db_table = 'review_responses'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Response to {self.review}"
    
    def save(self, *args, **kwargs):
        # Update review to indicate it has a response
        self.review.has_response = True
        self.review.save(update_fields=['has_response'])
        super().save(*args, **kwargs)


class ReviewHelpful(TimeStampedModel):
    """Track which users found reviews helpful"""
    
    review = models.ForeignKey(
        Review,
        on_delete=models.CASCADE,
        related_name='helpful_votes'
    )
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='helpful_review_votes'
    )
    
    is_helpful = models.BooleanField(
        default=True,
        help_text="True if helpful, False if not helpful"
    )
    
    class Meta:
        db_table = 'review_helpful'
        unique_together = [['review', 'user']]
        ordering = ['-created_at']
    
    def __str__(self):
        helpful_text = "helpful" if self.is_helpful else "not helpful"
        return f"{self.user.username} found review {helpful_text}"


class ReviewReport(TimeStampedModel):
    """Reports of inappropriate reviews"""
    
    review = models.ForeignKey(
        Review,
        on_delete=models.CASCADE,
        related_name='reports'
    )
    
    reporter = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='review_reports'
    )
    
    REPORT_REASONS = [
        ('spam', 'Spam'),
        ('offensive', 'Offensive Language'),
        ('fake', 'Fake Review'),
        ('irrelevant', 'Irrelevant Content'),
        ('personal', 'Personal Information'),
        ('other', 'Other')
    ]
    reason = models.CharField(
        max_length=20,
        choices=REPORT_REASONS
    )
    
    details = models.TextField(
        blank=True,
        help_text="Additional details about the report"
    )
    
    # Moderation
    is_resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_reports'
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)
    
    class Meta:
        db_table = 'review_reports'
        unique_together = [['review', 'reporter']]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Report by {self.reporter.username} on review {self.review.id}"
