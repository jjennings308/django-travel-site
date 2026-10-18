# ============================================
# rewards/models.py
# ============================================
from django.db import models
from django.core.validators import MinValueValidator
from apps.core.models import TimeStampedModel, UUIDModel
from django.conf import settings


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
