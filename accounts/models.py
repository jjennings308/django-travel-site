# accounts/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from core.models import TimeStampedModel, UUIDModel
from django.utils.translation import gettext_lazy as _


class User(AbstractUser, TimeStampedModel):
    """Custom user model extending Django's AbstractUser"""
    
    # Override email to make it required and unique
    email = models.EmailField(
        _('email address'),
        unique=True,
        help_text=_('Required. A valid email address.')
    )
    
    # Additional user fields
    date_of_birth = models.DateField(null=True, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    
    # User status
    is_verified = models.BooleanField(
        default=False,
        help_text="Email verification status"
    )
    is_premium = models.BooleanField(
        default=False,
        help_text="Premium subscription status"
    )
    premium_expires = models.DateTimeField(null=True, blank=True)
    
    # Privacy settings
    profile_visibility = models.CharField(
        max_length=20,
        choices=[
            ('public', 'Public'),
            ('friends', 'Friends Only'),
            ('private', 'Private')
        ],
        default='public'
    )
    
    USERNAME_FIELD = 'email'  # Use email for login instead of username
    REQUIRED_FIELDS = ['username', 'first_name', 'last_name']
    
    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
    
    def __str__(self):
        return f"{self.get_full_name()} ({self.email})"
    
    @property
    def age(self):
        """Calculate user's age"""
        if self.date_of_birth:
            from core.utils import calculate_age
            return calculate_age(self.date_of_birth)
        return None


class Profile(TimeStampedModel):
    """Extended user profile with travel preferences and bio"""
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile',
        primary_key=True
    )
    
    # Profile information
    bio = models.TextField(
        max_length=500,
        blank=True,
        help_text="Short bio about yourself"
    )
    avatar = models.ImageField(
        upload_to='avatars/%Y/%m/',
        null=True,
        blank=True,
        help_text="Profile picture"
    )
    cover_photo = models.ImageField(
        upload_to='covers/%Y/%m/',
        null=True,
        blank=True
    )
    
    # Location
    home_country = models.CharField(max_length=100, blank=True)
    home_city = models.CharField(max_length=100, blank=True)
    current_location = models.CharField(
        max_length=100,
        blank=True,
        help_text="Where you are right now"
    )
    
    # Travel stats (denormalized for performance)
    countries_visited_count = models.IntegerField(default=0)
    trips_completed_count = models.IntegerField(default=0)
    bucket_list_completed_count = models.IntegerField(default=0)
    
    # Social
    website = models.URLField(blank=True)
    instagram = models.CharField(max_length=100, blank=True)
    twitter = models.CharField(max_length=100, blank=True)
    
    class Meta:
        db_table = 'user_profiles'
    
    def __str__(self):
        return f"Profile: {self.user.get_full_name()}"


class UserPreferences(TimeStampedModel):
    """User preferences for travel style and notifications"""
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='preferences',
        primary_key=True
    )
    
    # Travel preferences
    BUDGET_CHOICES = [
        ('budget', 'Budget Traveler'),
        ('moderate', 'Moderate'),
        ('luxury', 'Luxury'),
        ('mixed', 'Mixed / Flexible')
    ]
    budget_preference = models.CharField(
        max_length=20,
        choices=BUDGET_CHOICES,
        default='moderate'
    )
    
    TRAVEL_STYLE_CHOICES = [
        ('adventure', 'Adventure'),
        ('relaxation', 'Relaxation'),
        ('cultural', 'Cultural Immersion'),
        ('foodie', 'Food & Dining'),
        ('nature', 'Nature & Wildlife'),
        ('urban', 'City Explorer'),
        ('backpacker', 'Backpacker'),
        ('family', 'Family Friendly')
    ]
    travel_styles = models.JSONField(
        default=list,
        help_text="List of preferred travel styles"
    )
    
    PACE_CHOICES = [
        ('slow', 'Slow - Few activities, lots of relaxation'),
        ('moderate', 'Moderate - Balanced itinerary'),
        ('fast', 'Fast - Packed schedule, see everything')
    ]
    travel_pace = models.CharField(
        max_length=20,
        choices=PACE_CHOICES,
        default='moderate'
    )
    
    # Activity preferences
    preferred_activities = models.JSONField(
        default=list,
        help_text="List of activity category IDs user prefers"
    )
    
    # Physical capabilities
    fitness_level = models.IntegerField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="1=Low, 5=Very High"
    )
    mobility_restrictions = models.BooleanField(
        default=False,
        help_text="User has mobility restrictions"
    )
    
    # Notification preferences
    email_notifications = models.BooleanField(default=True)
    push_notifications = models.BooleanField(default=True)
    marketing_emails = models.BooleanField(default=False)
    
    notify_bucket_list_reminders = models.BooleanField(default=True)
    notify_trip_updates = models.BooleanField(default=True)
    notify_event_reminders = models.BooleanField(default=True)
    notify_friend_activity = models.BooleanField(default=True)
    notify_recommendations = models.BooleanField(default=True)
    
    # Language and units
    LANGUAGE_CHOICES = [
        ('en', 'English'),
        ('es', 'Spanish'),
        ('fr', 'French'),
        ('de', 'German'),
        ('zh', 'Chinese'),
        ('ja', 'Japanese')
    ]
    language = models.CharField(
        max_length=5,
        choices=LANGUAGE_CHOICES,
        default='en'
    )
    
    UNIT_CHOICES = [
        ('metric', 'Metric (km, °C)'),
        ('imperial', 'Imperial (miles, °F)')
    ]
    units = models.CharField(
        max_length=10,
        choices=UNIT_CHOICES,
        default='imperial'
    )
    
    CURRENCY_CHOICES = [
        ('USD', 'US Dollar'),
        ('EUR', 'Euro'),
        ('GBP', 'British Pound'),
        ('JPY', 'Japanese Yen'),
        ('CAD', 'Canadian Dollar'),
        ('AUD', 'Australian Dollar')
    ]
    preferred_currency = models.CharField(
        max_length=3,
        choices=CURRENCY_CHOICES,
        default='USD'
    )
    
    timezone = models.CharField(
        max_length=50,
        default="UTC",
        help_text="IANA timezone (e.g. America/New_York)"
    )
    
    THEME_CHOICES = [
        ("default", "System Default"),
        ("light", "Light"),
        ("dark", "Dark"),
    ]

    theme = models.CharField(
        max_length=10,
        choices=THEME_CHOICES,
        default="default",
        help_text="UI theme preference"
    )

    class Meta:
        db_table = 'user_preferences'
        verbose_name = 'User Preference'
        verbose_name_plural = 'User Preferences'
    
    def __str__(self):
        return f"Preferences: {self.user.email}"