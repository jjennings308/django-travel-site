# recommendations/models.py
from django.db import models
from core.models import TimeStampedModel
from accounts.models import User
from activities.models import Activity
from locations.models import City
from events.models import Event
from trips.models import Trip
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.validators import MinValueValidator, MaxValueValidator


class RecommendationRule(TimeStampedModel):
    """Rules for generating recommendations"""
    
    name = models.CharField(
        max_length=200,
        unique=True,
        help_text="E.g., 'Similar Activities', 'Popular in City'"
    )
    description = models.TextField(blank=True)
    
    RULE_TYPES = [
        ('content_based', 'Content-Based'),
        ('collaborative', 'Collaborative Filtering'),
        ('popularity', 'Popularity-Based'),
        ('location_based', 'Location-Based'),
        ('user_preference', 'User Preference'),
        ('trending', 'Trending'),
        ('seasonal', 'Seasonal'),
        ('custom', 'Custom Logic')
    ]
    rule_type = models.CharField(
        max_length=20,
        choices=RULE_TYPES
    )
    
    # Target content types
    source_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name='recommendation_source_rules',
        help_text="What triggers this recommendation (e.g., Activity, City)"
    )
    
    target_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name='recommendation_target_rules',
        help_text="What gets recommended (e.g., Activity, Event)"
    )
    
    # Scoring
    base_score = models.IntegerField(
        default=50,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Base relevance score (0-100)"
    )
    
    weight = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=1.0,
        help_text="Weight multiplier for this rule"
    )
    
    # Conditions (stored as JSON)
    conditions = models.JSONField(
        default=dict,
        blank=True,
        help_text="Conditions that must be met for rule to apply"
    )
    
    # Settings
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this rule is currently active"
    )
    
    max_recommendations = models.IntegerField(
        default=10,
        help_text="Maximum recommendations to generate"
    )
    
    # Priority
    priority = models.IntegerField(
        default=0,
        help_text="Higher priority rules are evaluated first"
    )
    
    # Performance tracking
    usage_count = models.IntegerField(
        default=0,
        help_text="How many times this rule has been used"
    )
    average_ctr = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=0.0,
        help_text="Average click-through rate"
    )
    
    class Meta:
        db_table = 'recommendation_rules'
        ordering = ['-priority', 'name']
    
    def __str__(self):
        return f"{self.name} ({self.rule_type})"


class Recommendation(TimeStampedModel):
    """Generated recommendations for users"""
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='recommendations'
    )
    
    # What's being recommended (generic relation)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        help_text="Type of item being recommended"
    )
    object_id = models.PositiveIntegerField(
        help_text="ID of item being recommended"
    )
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Context (what triggered this recommendation)
    context_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name='recommendation_contexts',
        null=True,
        blank=True,
        help_text="What triggered this recommendation"
    )
    context_object_id = models.PositiveIntegerField(
        null=True,
        blank=True
    )
    context_object = GenericForeignKey('context_content_type', 'context_object_id')
    
    # Scoring
    relevance_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Calculated relevance score (0-100)"
    )
    
    confidence_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.0,
        help_text="Confidence in recommendation (0-100)"
    )
    
    # Source
    rule = models.ForeignKey(
        RecommendationRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recommendations'
    )
    
    generation_method = models.CharField(
        max_length=50,
        choices=[
            ('rule_based', 'Rule-Based'),
            ('ml_model', 'ML Model'),
            ('hybrid', 'Hybrid'),
            ('manual', 'Manual Curation')
        ],
        default='rule_based'
    )
    
    # Reasoning
    reason = models.CharField(
        max_length=300,
        blank=True,
        help_text="Why this was recommended (shown to user)"
    )
    
    explanation_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Detailed explanation data"
    )
    
    # Engagement tracking
    is_viewed = models.BooleanField(default=False)
    viewed_at = models.DateTimeField(null=True, blank=True)
    
    is_clicked = models.BooleanField(default=False)
    clicked_at = models.DateTimeField(null=True, blank=True)
    
    is_dismissed = models.BooleanField(default=False)
    dismissed_at = models.DateTimeField(null=True, blank=True)
    dismiss_reason = models.CharField(max_length=100, blank=True)
    
    is_saved = models.BooleanField(
        default=False,
        help_text="User saved/bookmarked this recommendation"
    )
    saved_at = models.DateTimeField(null=True, blank=True)
    
    # Conversion
    is_converted = models.BooleanField(
        default=False,
        help_text="User took desired action (added to bucket list, booked, etc.)"
    )
    converted_at = models.DateTimeField(null=True, blank=True)
    
    # Expiration
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When recommendation becomes stale"
    )
    
    # Display
    display_position = models.IntegerField(
        default=0,
        help_text="Position in recommendation list"
    )
    
    class Meta:
        db_table = 'recommendations'
        ordering = ['user', '-relevance_score', '-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', '-relevance_score']),
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['expires_at']),
        ]
        # Prevent duplicate recommendations
        unique_together = [['user', 'content_type', 'object_id', 'context_content_type', 'context_object_id']]
    
    def __str__(self):
        return f"Recommendation for {self.user.username}: {self.content_object}"
    
    def mark_viewed(self):
        """Mark recommendation as viewed"""
        if not self.is_viewed:
            from django.utils import timezone
            self.is_viewed = True
            self.viewed_at = timezone.now()
            self.save(update_fields=['is_viewed', 'viewed_at'])
    
    def mark_clicked(self):
        """Mark recommendation as clicked"""
        if not self.is_clicked:
            from django.utils import timezone
            self.is_clicked = True
            self.clicked_at = timezone.now()
            if not self.is_viewed:
                self.mark_viewed()
            self.save(update_fields=['is_clicked', 'clicked_at'])
    
    def mark_converted(self):
        """Mark recommendation as converted"""
        if not self.is_converted:
            from django.utils import timezone
            self.is_converted = True
            self.converted_at = timezone.now()
            self.save(update_fields=['is_converted', 'converted_at'])
    
    @property
    def is_expired(self):
        """Check if recommendation has expired"""
        if self.expires_at:
            from django.utils import timezone
            return timezone.now() > self.expires_at
        return False


class UserInterest(TimeStampedModel):
    """Track user interests for recommendations"""
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='interests'
    )
    
    # Interest subject (generic relation)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        help_text="Type of interest (Activity, City, etc.)"
    )
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Interest strength
    interest_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=50.0,
        help_text="Interest strength (0-100)"
    )
    
    # Tracking
    view_count = models.IntegerField(
        default=0,
        help_text="How many times user viewed this"
    )
    interaction_count = models.IntegerField(
        default=0,
        help_text="How many times user interacted with this"
    )
    
    last_interacted_at = models.DateTimeField(auto_now=True)
    
    # Source of interest
    INTEREST_SOURCES = [
        ('explicit', 'Explicit (user selected)'),
        ('implicit', 'Implicit (behavior)'),
        ('profile', 'Profile preferences'),
        ('bucket_list', 'Bucket list items'),
        ('completed', 'Completed activities')
    ]
    source = models.CharField(
        max_length=20,
        choices=INTEREST_SOURCES,
        default='implicit'
    )
    
    class Meta:
        db_table = 'user_interests'
        unique_together = [['user', 'content_type', 'object_id']]
        ordering = ['user', '-interest_score']
        indexes = [
            models.Index(fields=['user', '-interest_score']),
            models.Index(fields=['content_type', 'object_id']),
        ]
    
    def __str__(self):
        return f"{self.user.username}'s interest in {self.content_object} ({self.interest_score})"
    
    def increase_interest(self, amount=5.0):
        """Increase interest score"""
        self.interest_score = min(100.0, self.interest_score + amount)
        self.interaction_count += 1
        self.save()
    
    def decrease_interest(self, amount=5.0):
        """Decrease interest score"""
        self.interest_score = max(0.0, self.interest_score - amount)
        self.save()


class RecommendationFeedback(TimeStampedModel):
    """User feedback on recommendations"""
    
    recommendation = models.ForeignKey(
        Recommendation,
        on_delete=models.CASCADE,
        related_name='feedback'
    )
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='recommendation_feedback'
    )
    
    FEEDBACK_TYPES = [
        ('like', 'Like'),
        ('dislike', 'Dislike'),
        ('not_interested', 'Not Interested'),
        ('already_done', 'Already Done'),
        ('irrelevant', 'Not Relevant'),
        ('helpful', 'Helpful')
    ]
    feedback_type = models.CharField(
        max_length=20,
        choices=FEEDBACK_TYPES
    )
    
    comment = models.TextField(
        blank=True,
        help_text="Optional feedback comment"
    )
    
    class Meta:
        db_table = 'recommendation_feedback'
        unique_together = [['recommendation', 'user']]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username}'s feedback: {self.feedback_type}"


class RecommendationPerformance(TimeStampedModel):
    """Track performance metrics for recommendations"""
    
    rule = models.ForeignKey(
        RecommendationRule,
        on_delete=models.CASCADE,
        related_name='performance_metrics'
    )
    
    # Time period
    period_start = models.DateTimeField(db_index=True)
    period_end = models.DateTimeField(db_index=True)
    
    # Metrics
    total_generated = models.IntegerField(
        default=0,
        help_text="Total recommendations generated"
    )
    total_viewed = models.IntegerField(default=0)
    total_clicked = models.IntegerField(default=0)
    total_converted = models.IntegerField(default=0)
    total_dismissed = models.IntegerField(default=0)
    
    # Calculated rates
    view_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=0.0,
        help_text="Percentage viewed"
    )
    click_through_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=0.0,
        help_text="Percentage clicked"
    )
    conversion_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=0.0,
        help_text="Percentage converted"
    )
    
    # Average scores
    avg_relevance_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.0
    )
    avg_confidence_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.0
    )
    
    class Meta:
        db_table = 'recommendation_performance'
        ordering = ['-period_end']
        indexes = [
            models.Index(fields=['rule', '-period_end']),
            models.Index(fields=['period_start', 'period_end']),
        ]
    
    def __str__(self):
        return f"{self.rule.name} performance ({self.period_start.date()} to {self.period_end.date()})"