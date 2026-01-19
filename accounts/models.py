# accounts/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.utils import timezone
from core.models import TimeStampedModel
from django.utils.translation import gettext_lazy as _


class User(AbstractUser, TimeStampedModel):
    """Custom user model with username and email"""
    
    # Unique identifiers
    username = models.CharField(
        max_length=30,
        unique=True,
        validators=[
            RegexValidator(
                r'^[a-zA-Z0-9_]+$',
                'Username can only contain letters, numbers, and underscores'
            )
        ],
        help_text='Unique username for your profile URL'
    )
    
    email = models.EmailField(
        _('email address'),
        unique=True,
        help_text=_('Required. A valid email address.')
    )
    
    # Additional user fields
    date_of_birth = models.DateField(null=True, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    
    # Subscription tier system
    class SubscriptionTier(models.TextChoices):
        FREE = 'free', 'Free Member'
        PLUS = 'plus', 'Plus Member'
        GOLD = 'gold', 'Gold Member'
    
    subscription_tier = models.CharField(
        max_length=10,
        choices=SubscriptionTier.choices,
        default=SubscriptionTier.FREE,
        help_text='Membership subscription level'
    )
    
    subscription_expires = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When paid subscription expires (null for free tier)'
    )
    
    # User status
    is_verified = models.BooleanField(
        default=False,
        help_text="Email verification status"
    )
    
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
    
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email', 'first_name', 'last_name']
    
    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        permissions = [
            ("can_access_staff_dashboard", "Can access staff dashboard"),
        ]
    
    def __str__(self):
        return f"{self.get_full_name()} (@{self.username})"
    
    @property
    def age(self):
        """Calculate user's age"""
        if self.date_of_birth:
            from core.utils import calculate_age
            return calculate_age(self.date_of_birth)
        return None
    
    @property
    def is_premium(self):
        """Check if user has active paid subscription"""
        if self.subscription_tier == self.SubscriptionTier.FREE:
            return False
        
        if self.subscription_expires and self.subscription_expires < timezone.now():
            return False
        
        return True
    
    @property
    def is_vendor(self):
        """Check if user has vendor capabilities"""
        return self.groups.filter(name='Vendors').exists()
    
    @property
    def is_content_provider(self):
        """Check if user has content provider capabilities"""
        return self.groups.filter(name='Content Providers').exists()
    
    @property
    def can_access_staff(self):
        return self.is_superuser or self.has_perm("accounts.can_access_staff_dashboard")
    
    @property
    def can_access_vendor_dashboard(self):
        """Can access vendor features"""
        return self.is_vendor or self.is_staff or self.is_superuser
    
    @property
    def can_access_content_dashboard(self):
        """Can access content provider features"""
        return self.is_content_provider or self.is_staff or self.is_superuser


class Profile(TimeStampedModel):
    """Extended user profile with travel info and bio"""
    
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


class TravelPreferences(TimeStampedModel):
    """Travel style preferences - shown on profile"""
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='travel_preferences',
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
    
    class Meta:
        db_table = 'travel_preferences'
        verbose_name = 'Travel Preference'
        verbose_name_plural = 'Travel Preferences'
    
    def __str__(self):
        return f"Travel Preferences: {self.user.username}"


class AccountSettings(TimeStampedModel):
    """Account settings - notifications, regional, privacy"""
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='settings',
        primary_key=True
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
        ("brand", "ShareBucketList Theme"),
        ("light", "Light"),
        ("dark", "Dark"),
    ]
    theme = models.CharField(
        max_length=10,
        choices=THEME_CHOICES,
        default="brand",
        help_text="UI theme preference"
    )
    
    # Privacy settings
    show_email_on_profile = models.BooleanField(
        default=False,
        help_text="Display email address on public profile"
    )
    show_trips_publicly = models.BooleanField(
        default=True,
        help_text="Allow others to see your trips"
    )
    allow_friend_requests = models.BooleanField(
        default=True,
        help_text="Allow others to send friend requests"
    )
    
    class Meta:
        db_table = 'account_settings'
        verbose_name = 'Account Settings'
        verbose_name_plural = 'Account Settings'
    
    def __str__(self):
        return f"Settings: {self.user.username}"


class RoleRequest(TimeStampedModel):
    """Track requests for additional roles (vendor, content provider)"""
    
    class RequestedRole(models.TextChoices):
        VENDOR = 'vendor', 'Vendor'
        CONTENT_PROVIDER = 'content_provider', 'Content Provider'
    
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending Review'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        REVOKED = 'revoked', 'Revoked'
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='role_requests'
    )
    
    requested_role = models.CharField(
        max_length=20,
        choices=RequestedRole.choices
    )
    
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    
    # Application details
    business_name = models.CharField(
        max_length=200,
        blank=True,
        help_text='Business/brand name (for vendors)'
    )
    business_description = models.TextField(
        help_text='Tell us about your business/content'
    )
    website = models.URLField(blank=True)
    business_license = models.CharField(
        max_length=100,
        blank=True,
        help_text='Business license number (if applicable)'
    )
    supporting_documents = models.FileField(
        upload_to='role_requests/%Y/%m/',
        null=True,
        blank=True,
        help_text='Upload verification documents (license, portfolio, etc.)'
    )
    
    # Review details
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_role_requests'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(
        blank=True,
        help_text='Internal notes about approval/rejection'
    )
    rejection_reason = models.TextField(
        blank=True,
        help_text='Reason shown to user if rejected'
    )
    
    class Meta:
        db_table = 'role_requests'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'requested_role', 'status']),
            models.Index(fields=['status', 'created_at']),
        ]
        constraints = [
            # Prevent duplicate pending requests
            models.UniqueConstraint(
                fields=['user', 'requested_role'],
                condition=models.Q(status='pending'),
                name='unique_pending_role_request'
            )
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.requested_role} ({self.status})"
    
    def approve(self, reviewed_by):
        """Approve the role request and grant access"""
        from django.contrib.auth.models import Group
        
        self.status = self.Status.APPROVED
        self.reviewed_by = reviewed_by
        self.reviewed_at = timezone.now()
        self.save()
        
        # Add user to appropriate group
        if self.requested_role == self.RequestedRole.VENDOR:
            group, _ = Group.objects.get_or_create(name='Vendors')
            self.user.groups.add(group)
            
            # Create vendor profile if it doesn't exist
            VendorProfile.objects.get_or_create(
                user=self.user,
                defaults={
                    'business_name': self.business_name,
                    'business_description': self.business_description,
                    'website': self.website,
                    'business_license': self.business_license,
                }
            )
        
        elif self.requested_role == self.RequestedRole.CONTENT_PROVIDER:
            group, _ = Group.objects.get_or_create(name='Content Providers')
            self.user.groups.add(group)
            
            # Create content provider profile
            ContentProviderProfile.objects.get_or_create(
                user=self.user,
                defaults={
                    'portfolio_url': self.website,
                    'bio': self.business_description,
                }
            )
        
        # TODO: Send approval email to user
    
    def reject(self, reviewed_by, reason):
        """Reject the role request"""
        self.status = self.Status.REJECTED
        self.reviewed_by = reviewed_by
        self.reviewed_at = timezone.now()
        self.rejection_reason = reason
        self.save()
        
        # TODO: Send rejection email to user


class VendorProfile(TimeStampedModel):
    """Extended profile for vendors"""
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='vendor_profile',
        primary_key=True
    )
    
    # Business information
    business_name = models.CharField(max_length=200)
    business_description = models.TextField()
    business_license = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)
    
    # Verification
    class VerificationStatus(models.TextChoices):
        PENDING = 'pending', 'Pending Verification'
        VERIFIED = 'verified', 'Verified'
        SUSPENDED = 'suspended', 'Suspended'
    
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.VERIFIED
    )
    
    # Business stats
    total_listings = models.IntegerField(default=0)
    average_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0.00
    )
    total_bookings = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'vendor_profiles'
    
    def __str__(self):
        return f"Vendor: {self.business_name}"


class ContentProviderProfile(TimeStampedModel):
    """Extended profile for content providers"""
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='content_provider_profile',
        primary_key=True
    )
    
    # Portfolio information
    portfolio_url = models.URLField(blank=True)
    bio = models.TextField(help_text='Your background and expertise')
    specializations = models.JSONField(
        default=list,
        help_text='List of content specializations (photography, writing, video, etc.)'
    )
    
    # Stats
    total_contributions = models.IntegerField(default=0)
    content_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0.00
    )
    
    class Meta:
        db_table = 'content_provider_profiles'
    
    def __str__(self):
        return f"Content Provider: {self.user.username}"


# Keep old model for backward compatibility during migration
class UserPreferences(TimeStampedModel):
    """DEPRECATED - Use TravelPreferences and AccountSettings instead"""
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='preferences',
        primary_key=True
    )
    
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
    
    preferred_activities = models.JSONField(
        default=list,
        help_text="List of activity category IDs user prefers"
    )
    
    fitness_level = models.IntegerField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="1=Low, 5=Very High"
    )
    mobility_restrictions = models.BooleanField(
        default=False,
        help_text="User has mobility restrictions"
    )
    
    email_notifications = models.BooleanField(default=True)
    push_notifications = models.BooleanField(default=True)
    marketing_emails = models.BooleanField(default=False)
    
    notify_bucket_list_reminders = models.BooleanField(default=True)
    notify_trip_updates = models.BooleanField(default=True)
    notify_event_reminders = models.BooleanField(default=True)
    notify_friend_activity = models.BooleanField(default=True)
    notify_recommendations = models.BooleanField(default=True)
    
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
        ("brand", "ShareBucketList Theme"),
        ("light", "Light"),
        ("dark", "Dark"),
    ]
    theme = models.CharField(
        max_length=10,
        choices=THEME_CHOICES,
        default="brand",
        help_text="UI theme preference"
    )

    class Meta:
        db_table = 'user_preferences'
        verbose_name = 'User Preference (Deprecated)'
        verbose_name_plural = 'User Preferences (Deprecated)'
    
    def __str__(self):
        return f"Preferences: {self.user.username}"
