# reviews/models.py
from django.db import models
from apps.core.models import TimeStampedModel
from django.conf import settings
from apps.vendors.models import Vendor
from apps.activities.models import Activity
from apps.events.models import Event
from apps.locations.models import City, POI
from apps.trips.models import Trip
from django.core.validators import MinValueValidator, MaxValueValidator


class Review(TimeStampedModel):
    """User reviews for various content types"""
    
    # Reviewer
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,  # a deleted account's reviews stay, as "A former member" (R13)
        null=True,
        blank=True,
        related_name='reviews'
    )
    
    # What's being reviewed (only ONE should be set)
    REVIEW_TYPES = [
        ('vendor', 'Vendor'),
        ('activity', 'Activity'),
        ('event', 'Event'),
        ('location', 'City'),
        ('poi', 'Place'),
        ('trip', 'Trip'),
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
    
    poi = models.ForeignKey(
        POI,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='reviews',
        verbose_name='place'
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
        help_text="Shown on the site; untick to hide (also hidden automatically after 3 open reports)"
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
            ['user', 'poi'],
            ['user', 'trip'],
        ]
    
    def __str__(self):
        target = self.get_review_target_name()
        return f"{self.author_name}'s review of {target} ({self.rating}★)"

    @property
    def author_name(self):
        """@username, or "A former member" once the account is deleted (site roadmap R13)."""
        return f"@{self.user.username}" if self.user_id else "A former member"
    
    @property
    def target(self):
        """The activity, event, city or place reviewed (None for vendor/trip/site reviews)."""
        return self.activity or self.event or self.location or self.poi

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
        elif self.poi:
            return self.poi.name
        elif self.trip:
            return self.trip.name
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
        
        references = sum([
            bool(self.vendor),
            bool(self.activity),
            bool(self.event),
            bool(self.location),
            bool(self.poi),
            bool(self.trip)
        ])
        
        if references == 0:
            raise ValidationError('Must specify what is being reviewed')
        elif references > 1:
            raise ValidationError('Can only review one item at a time')


class ReviewReport(TimeStampedModel):
    """Reports of inappropriate reviews"""
    
    review = models.ForeignKey(
        Review,
        on_delete=models.CASCADE,
        related_name='reports'
    )
    
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
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
        settings.AUTH_USER_MODEL,
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


class TripRatingPrompt(models.Model):
    """One person was asked to rate a finished trip's places (site roadmap R17); asked once, ever.
    ``answered_at`` / ``skipped_at`` record what they did (``reviews/trip_ratings.py``). Lives in
    reviews because reviews may use trips, never the other way round."""

    trip = models.ForeignKey("trips.Trip", on_delete=models.CASCADE, related_name="rating_prompts")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trip_rating_prompts")
    asked_at = models.DateTimeField(auto_now_add=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    skipped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "reviews_tripratingprompt"
        constraints = [models.UniqueConstraint(fields=["trip", "user"], name="tripratingprompt_once")]
