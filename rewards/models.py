# ============================================
# rewards/models.py
# ============================================
from django.db import models
from django.core.validators import MinValueValidator
from core.models import TimeStampedModel, UUIDModel
from accounts.models import User


class RewardsProgramType(models.TextChoices):
    """Types of rewards programs"""
    AIRLINE = 'airline', 'Airline'
    HOTEL = 'hotel', 'Hotel'
    CAR_RENTAL = 'car_rental', 'Car Rental'
    CREDIT_CARD = 'credit_card', 'Credit Card'
    TRAIN = 'train', 'Train/Rail'
    CRUISE = 'cruise', 'Cruise Line'
    OTHER = 'other', 'Other'


class RewardsProgram(TimeStampedModel):
    """Master list of rewards programs"""
    
    name = models.CharField(
        max_length=200,
        help_text="e.g., United MileagePlus, Marriott Bonvoy"
    )
    program_type = models.CharField(
        max_length=20,
        choices=RewardsProgramType.choices,
        default=RewardsProgramType.OTHER
    )
    company = models.CharField(
        max_length=200,
        help_text="e.g., United Airlines, Marriott"
    )
    website = models.URLField(blank=True)
    logo = models.ImageField(
        upload_to='rewards_logos/',
        null=True,
        blank=True
    )
    
    # Optional: store common tier names
    tier_names = models.JSONField(
        default=list,
        blank=True,
        help_text="List of tier names, e.g., ['Silver', 'Gold', 'Platinum']"
    )
    
    # Program details
    description = models.TextField(
        blank=True,
        help_text="Brief description of the program"
    )
    
    # Meta
    is_active = models.BooleanField(
        default=True,
        help_text="Is this program still active/operational?"
    )
    display_order = models.IntegerField(
        default=0,
        help_text="Order to display in lists (lower = first)"
    )
    
    class Meta:
        db_table = 'rewards_programs'
        ordering = ['display_order', 'company', 'name']
        unique_together = [['name', 'company']]
        indexes = [
            models.Index(fields=['program_type', 'is_active']),
            models.Index(fields=['display_order']),
        ]
    
    def __str__(self):
        return f"{self.company} - {self.name}"
    
    @property
    def member_count(self):
        # If queryset annotated _member_count, use it; otherwise fall back
        return getattr(self, "_member_count", self.memberships.count())


class UserRewardsMembership(TimeStampedModel, UUIDModel):
    """User's membership in a rewards program"""
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='rewards_memberships'
    )
    program = models.ForeignKey(
        RewardsProgram,
        on_delete=models.CASCADE,
        related_name='memberships'
    )
    
    # Membership details
    member_number = models.CharField(
        max_length=100,
        help_text="Your membership/account number"
    )
    member_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Name on the account (if different from profile)"
    )
    
    # Status tracking
    current_tier = models.CharField(
        max_length=50,
        blank=True,
        help_text="e.g., Gold, Platinum"
    )
    points_balance = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Current points/miles balance (optional)"
    )
    tier_expires = models.DateField(
        null=True,
        blank=True,
        help_text="When current tier status expires"
    )
    
    # Login credentials (optional)
    username = models.CharField(
        max_length=200,
        blank=True,
        help_text="Login username for this program"
    )
    # Note: In production, use encryption for password storage
    # from django_cryptography.fields import encrypt
    # password = encrypt(models.CharField(max_length=200, blank=True))
    
    # Preferences
    is_primary = models.BooleanField(
        default=False,
        help_text="Primary program of this type (e.g., preferred airline)"
    )
    notes = models.TextField(
        blank=True,
        help_text="Personal notes about this membership"
    )
    
    # Display settings
    show_on_profile = models.BooleanField(
        default=True,
        help_text="Show this membership on your public profile"
    )
    display_order = models.IntegerField(
        default=0,
        help_text="Order to display on profile (lower = first)"
    )
    
    # Notifications
    notify_on_expiration = models.BooleanField(
        default=True,
        help_text="Notify when tier status is about to expire"
    )
    expiration_notice_days = models.IntegerField(
        default=30,
        validators=[MinValueValidator(1)],
        help_text="Days before expiration to send notification"
    )
    
    class Meta:
        db_table = 'user_rewards_memberships'
        ordering = ['display_order', 'program__company']
        unique_together = [['user', 'program']]
        indexes = [
            models.Index(fields=['user', 'is_primary']),
            models.Index(fields=['user', 'show_on_profile']),
            models.Index(fields=['user', 'program']),
        ]
        verbose_name = 'Rewards Membership'
        verbose_name_plural = 'Rewards Memberships'
    
    def __str__(self):
        return f"{self.user.email} - {self.program.name}"
    
    def save(self, *args, **kwargs):
        # If this is set as primary, unset other primary memberships of same type
        if self.is_primary:
            UserRewardsMembership.objects.filter(
                user=self.user,
                program__program_type=self.program.program_type,
                is_primary=True
            ).exclude(id=self.id).update(is_primary=False)
        super().save(*args, **kwargs)
    
    @property
    def is_tier_expiring_soon(self):
        """Check if tier status is expiring within notice period"""
        if not self.tier_expires or not self.notify_on_expiration:
            return False
        
        from django.utils import timezone
        from datetime import timedelta
        
        days_until_expiration = (self.tier_expires - timezone.now().date()).days
        return 0 < days_until_expiration <= self.expiration_notice_days
