# activities/models.py
from django.db import models
from core.models import TimeStampedModel, SlugMixin, FeaturedContentMixin
from django.core.validators import MinValueValidator, MaxValueValidator


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


class Activity(TimeStampedModel, SlugMixin, FeaturedContentMixin):
    """Specific activities users can do"""
    
    category = models.ForeignKey(
        ActivityCategory,
        on_delete=models.PROTECT,
        related_name='activities'
    )
    
    name = models.CharField(
        max_length=200,
        help_text="E.g., Skydiving, Wine Tasting, Scuba Diving"
    )
    description = models.TextField(
        help_text="Detailed description of the activity"
    )
    short_description = models.CharField(
        max_length=300,
        blank=True,
        help_text="Brief description for cards/lists"
    )
    
    # Difficulty and requirements
    SKILL_LEVELS = [
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
        ('expert', 'Expert')
    ]
    skill_level = models.CharField(
        max_length=20,
        choices=SKILL_LEVELS,
        default='beginner'
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
        ('multi_day', 'Multi-Day')
    ]
    duration_category = models.CharField(
        max_length=20,
        choices=DURATION_CATEGORIES,
        default='short'
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
        ('luxury', 'Luxury ($$$$)')
    ]
    cost_level = models.CharField(
        max_length=20,
        choices=COST_LEVELS,
        default='moderate'
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
        help_text="List of best seasons for this activity"
    )
    
    indoor_outdoor = models.CharField(
        max_length=20,
        choices=[
            ('indoor', 'Indoor'),
            ('outdoor', 'Outdoor'),
            ('both', 'Both')
        ],
        default='outdoor'
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
    wheelchair_accessible = models.BooleanField(default=False)
    suitable_for_children = models.BooleanField(default=True)
    
    # Safety
    risk_level = models.CharField(
        max_length=20,
        choices=[
            ('low', 'Low Risk'),
            ('moderate', 'Moderate Risk'),
            ('high', 'High Risk'),
            ('extreme', 'Extreme Risk')
        ],
        default='low'
    )
    
    safety_notes = models.TextField(
        blank=True,
        help_text="Important safety information"
    )
    
    # Stats
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
    average_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(5)]
    )
    review_count = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'activities'
        verbose_name_plural = 'Activities'
        ordering = ['-popularity_score', 'name']
        indexes = [
            models.Index(fields=['category', 'skill_level']),
            models.Index(fields=['cost_level']),
            models.Index(fields=['-popularity_score']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.category.name})"
    
    def save(self, *args, **kwargs):
        if not self.slug:
            from core.utils import generate_unique_slug
            self.slug = generate_unique_slug(Activity, self.name, self.id)
        super().save(*args, **kwargs)


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