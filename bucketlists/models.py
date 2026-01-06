# bucketlists/models.py
from django.db import models
from core.models import TimeStampedModel
from accounts.models import User
from activities.models import Activity
from locations.models import City  # CORRECTED: Use City instead of Location
from events.models import Event
from django.core.validators import MinValueValidator, MaxValueValidator


class BucketListItem(TimeStampedModel):
    """User's bucket list items - references to activities, locations, or events they want to experience"""
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='bucket_list_items'
    )
    
    # Reference to global content (only ONE should be set)
    activity = models.ForeignKey(
        Activity,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='bucket_list_items',
        help_text="Activity to experience"
    )
    
    city = models.ForeignKey(  # CORRECTED: Changed from 'location' to 'city'
        City,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='bucket_list_items',
        help_text="City/destination to visit"
    )
    
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='bucket_list_items',
        help_text="Event to attend"
    )
    
    # Custom items (when user creates their own, not from catalog)
    custom_title = models.CharField(
        max_length=200,
        blank=True,
        help_text="For custom bucket list items not in catalog"
    )
    custom_description = models.TextField(
        blank=True,
        help_text="Description for custom items"
    )
    
    # User customization
    personal_notes = models.TextField(
        blank=True,
        help_text="Personal notes, reasons, memories"
    )
    
    # Planning
    target_date = models.DateField(
        null=True,
        blank=True,
        help_text="When user hopes to complete this"
    )
    target_season = models.CharField(
        max_length=20,
        choices=[
            ('spring', 'Spring'),
            ('summer', 'Summer'),
            ('fall', 'Fall'),
            ('winter', 'Winter'),
            ('anytime', 'Anytime')
        ],
        default='anytime',
        help_text="Best time to do this"
    )
    
    estimated_budget = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="User's estimated budget in their currency"
    )
    budget_currency = models.CharField(max_length=3, default='USD')
    
    # Priority and status
    PRIORITY_CHOICES = [
        (1, 'Low'),
        (2, 'Medium'),
        (3, 'High'),
        (4, 'Very High'),
        (5, 'Must Do!')
    ]
    priority = models.IntegerField(
        choices=PRIORITY_CHOICES,
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    
    STATUS_CHOICES = [
        ('wishlist', 'Wishlist'),
        ('researching', 'Researching'),
        ('planning', 'Planning'),
        ('booked', 'Booked'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('abandoned', 'Abandoned')
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='wishlist',
        db_index=True
    )
    
    # Completion
    completed_date = models.DateField(
        null=True,
        blank=True,
        help_text="When user completed this item"
    )
    completion_notes = models.TextField(
        blank=True,
        help_text="Thoughts/reflections after completing"
    )
    
    # Rating after completion
    user_rating = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="User's rating after completing"
    )
    
    # Sharing
    is_public = models.BooleanField(
        default=True,
        help_text="Whether this item is visible to others"
    )
    
    # Travel companions
    with_who = models.CharField(
        max_length=100,
        blank=True,
        help_text="Who user wants to do this with"
    )
    
    # Inspiration source
    inspiration_source = models.CharField(
        max_length=200,
        blank=True,
        help_text="Where they got the idea (friend, blog, movie, etc.)"
    )
    
    # Reminders
    reminder_enabled = models.BooleanField(
        default=False,
        help_text="Send reminders about this item"
    )
    next_reminder_date = models.DateField(
        null=True,
        blank=True
    )
    
    # Tags
    tags = models.JSONField(
        default=list,
        blank=True,
        help_text="User's custom tags"
    )
    
    # Display order
    display_order = models.IntegerField(
        default=0,
        help_text="User's custom ordering"
    )
    
    class Meta:
        db_table = 'bucket_list_items'
        ordering = ['user', '-priority', 'display_order']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['user', '-priority']),
            models.Index(fields=['status', 'target_date']),
        ]
    
    def __str__(self):
        if self.custom_title:
            return f"{self.user.username}'s: {self.custom_title}"
        elif self.activity:
            return f"{self.user.username}'s: {self.activity.name}"
        elif self.city:  # CORRECTED
            return f"{self.user.username}'s: {self.city.name}"
        elif self.event:
            return f"{self.user.username}'s: {self.event.name}"
        return f"{self.user.username}'s bucket list item"
    
    @property
    def title(self):
        """Get the display title for this item"""
        if self.custom_title:
            return self.custom_title
        elif self.activity:
            return self.activity.name
        elif self.city:  # CORRECTED
            return self.city.name
        elif self.event:
            return self.event.name
        return "Untitled Item"
    
    @property
    def is_completed(self):
        """Check if item is completed"""
        return self.status == 'completed' and self.completed_date is not None
    
    def complete(self, completion_date=None, notes='', rating=None):
        """Mark item as completed"""
        from django.utils import timezone
        self.status = 'completed'
        self.completed_date = completion_date or timezone.now().date()
        if notes:
            self.completion_notes = notes
        if rating:
            self.user_rating = rating
        self.save()
    
    def clean(self):
        """Validate that exactly one content reference is set (or custom_title)"""
        from django.core.exceptions import ValidationError
        
        references = sum([
            bool(self.activity),
            bool(self.city),  # CORRECTED
            bool(self.event),
            bool(self.custom_title)
        ])
        
        if references == 0:
            raise ValidationError('Must specify activity, city, event, or custom title')
        elif references > 1:
            raise ValidationError('Can only specify one of: activity, city, event, or custom title')


class BucketListCategory(TimeStampedModel):
    """User-created categories to organize their bucket list"""
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='bucket_list_categories'
    )
    
    name = models.CharField(
        max_length=100,
        help_text="E.g., 'Adventure Goals', 'European Cities', 'Food Experiences'"
    )
    description = models.TextField(blank=True)
    
    color = models.CharField(
        max_length=7,
        default='#3B82F6',
        help_text="Hex color code for visual organization"
    )
    icon = models.CharField(
        max_length=50,
        blank=True,
        help_text="Icon name or emoji"
    )
    
    display_order = models.IntegerField(default=0)
    
    # Stats
    item_count = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'bucket_list_categories'
        verbose_name_plural = 'Bucket List Categories'
        unique_together = [['user', 'name']]
        ordering = ['user', 'display_order', 'name']
    
    def __str__(self):
        return f"{self.user.username}'s {self.name}"


class BucketListItemCategory(models.Model):
    """Many-to-many relationship between items and categories"""
    
    item = models.ForeignKey(
        BucketListItem,
        on_delete=models.CASCADE,
        related_name='category_memberships'
    )
    category = models.ForeignKey(
        BucketListCategory,
        on_delete=models.CASCADE,
        related_name='item_memberships'
    )
    
    added_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'bucket_list_item_categories'
        unique_together = [['item', 'category']]
    
    def __str__(self):
        return f"{self.item.title} in {self.category.name}"


class BucketListMilestone(TimeStampedModel):
    """Track user milestones and achievements"""
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='bucket_list_milestones'
    )
    
    MILESTONE_TYPES = [
        ('items_added', 'Items Added'),
        ('items_completed', 'Items Completed'),
        ('countries_visited', 'Countries Visited'),
        ('activities_completed', 'Activities Completed'),
        ('events_attended', 'Events Attended'),
        ('custom', 'Custom Milestone')
    ]
    milestone_type = models.CharField(
        max_length=20,
        choices=MILESTONE_TYPES
    )
    
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # Target
    target_count = models.IntegerField(
        help_text="Target number to achieve"
    )
    current_count = models.IntegerField(
        default=0,
        help_text="Current progress"
    )
    
    # Achievement
    is_achieved = models.BooleanField(default=False)
    achieved_date = models.DateTimeField(null=True, blank=True)
    
    # Reward/badge
    badge_icon = models.CharField(max_length=50, blank=True)
    badge_color = models.CharField(max_length=7, default='#10B981')
    
    class Meta:
        db_table = 'bucket_list_milestones'
        ordering = ['user', '-is_achieved', 'milestone_type']
    
    def __str__(self):
        return f"{self.user.username}: {self.title} ({self.current_count}/{self.target_count})"
    
    @property
    def progress_percentage(self):
        """Calculate progress percentage"""
        if self.target_count > 0:
            return min(100, (self.current_count / self.target_count) * 100)
        return 0
    
    def check_achievement(self):
        """Check if milestone has been achieved"""
        if not self.is_achieved and self.current_count >= self.target_count:
            from django.utils import timezone
            self.is_achieved = True
            self.achieved_date = timezone.now()
            self.save()
            return True
        return False