# events/models.py
from django.conf import settings
from django.db import models
from django.db.models import Q
from apps.core.models import TimeStampedModel, SlugMixin, FeaturedContentMixin
from django.core.validators import MinValueValidator, MaxValueValidator
from apps.locations.models import City, Country, POI
from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import Approvable, ApprovalStatus
from django.utils import timezone


class EventQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Events ``user`` may see: approved ones, plus their own at any stage; staff see all."""
        if user is not None and user.is_authenticated and user.is_staff:
            return self
        approved = Q(approval_status=ApprovalStatus.APPROVED)
        if user is not None and user.is_authenticated:
            return self.filter(approved | Q(created_by=user))
        return self.filter(approved)


class Event(TimeStampedModel, SlugMixin, FeaturedContentMixin, Approvable):
    """Scheduled events. User-submitted events are visible only to their creator (and
    staff) until approved through the approval system, like activities."""

    objects = EventQuerySet.as_manager()

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_events',
        help_text="Who added this event (blank for admin-created events)",
    )
    
    # Basic information
    name = models.CharField(max_length=200)
    # Shared with activities: one category list for ideas (activities) and their
    # dated occurrences (events). See activities.0008 / events.0005.
    category = models.ForeignKey(
        ActivityCategory,
        on_delete=models.PROTECT,
        related_name='events'
    )
    
    description = models.TextField()
    short_description = models.CharField(
        max_length=300,
        blank=True,
        help_text="Brief description for cards/lists"
    )
    
    # Location
    city = models.ForeignKey(
        City,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='events',
        help_text="Catalogue city. Leave empty and fill country + location_text if the city isn't listed yet."
    )
    # When the city isn't in the catalogue yet: where the submitter says it is.
    # Staff link it to a City (existing or newly created) from the event page.
    country = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='events_unlinked',
        help_text="Country, when the city isn't in the catalogue"
    )
    location_text = models.CharField(
        max_length=200,
        blank=True,
        help_text="City / town as typed by the submitter, when it isn't in the catalogue"
    )
    poi = models.ForeignKey(
        POI,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='events',
        help_text="Specific venue/location"
    )
    
    venue_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Venue name if not a POI"
    )
    venue_address = models.CharField(max_length=300, blank=True)
    
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True
    )
    
    # Timing
    start_date = models.DateField(db_index=True)
    end_date = models.DateField(
        null=True,
        blank=True,
        help_text="For multi-day events"
    )
    
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    
    timezone = models.CharField(
        max_length=50,
        blank=True,
        help_text="IANA timezone"
    )
    
    is_all_day = models.BooleanField(default=False)
    
    # Recurrence
    is_recurring = models.BooleanField(
        default=False,
        help_text="Whether this event repeats"
    )
    
    RECURRENCE_TYPES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly')
    ]
    recurrence_type = models.CharField(
        max_length=20,
        choices=RECURRENCE_TYPES,
        blank=True
    )
    recurrence_end_date = models.DateField(null=True, blank=True)
    
    # Related activity
    related_activity = models.ForeignKey(
        Activity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='events',
        help_text="If event is related to a specific activity"
    )
    
    # Event details
    organizer = models.CharField(
        max_length=200,
        blank=True,
        help_text="Event organizer name"
    )
    
    EVENT_TYPES = [
        ('public', 'Public Event'),
        ('ticketed', 'Ticketed Event'),
        ('invite_only', 'Invite Only'),
        ('members_only', 'Members Only')
    ]
    event_type = models.CharField(
        max_length=20,
        choices=EVENT_TYPES,
        default='public'
    )
    
    # Capacity and attendance
    capacity = models.IntegerField(
        null=True,
        blank=True,
        help_text="Maximum attendance"
    )
    expected_attendance = models.IntegerField(
        null=True,
        blank=True,
        help_text="Expected number of attendees"
    )
    
    AGE_RESTRICTIONS = [
        ('all_ages', 'All Ages'),
        ('family', 'Family Friendly'),
        ('18+', '18+'),
        ('21+', '21+')
    ]
    age_restriction = models.CharField(
        max_length=20,
        choices=AGE_RESTRICTIONS,
        default='all_ages'
    )
    
    # Ticketing
    is_free = models.BooleanField(default=False)
    
    ticket_price_min = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Minimum ticket price"
    )
    ticket_price_max = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Maximum ticket price"
    )
    currency = models.CharField(max_length=3, default='USD')
    
    ticket_url = models.URLField(
        blank=True,
        help_text="URL to purchase tickets"
    )
    
    tickets_available = models.BooleanField(
        default=True,
        help_text="Whether tickets are currently available"
    )
    sold_out = models.BooleanField(default=False)
    
    # Registration
    registration_required = models.BooleanField(default=False)
    registration_url = models.URLField(blank=True)
    registration_deadline = models.DateTimeField(null=True, blank=True)
    
    # Contact and links
    website = models.URLField(blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    
    facebook_event_url = models.URLField(blank=True)
    instagram_handle = models.CharField(max_length=100, blank=True)
    
    # Event characteristics
    indoor_outdoor = models.CharField(
        max_length=20,
        choices=[
            ('indoor', 'Indoor'),
            ('outdoor', 'Outdoor'),
            ('both', 'Both')
        ],
        blank=True
    )
    
    wheelchair_accessible = models.BooleanField(default=False)
    parking_available = models.BooleanField(default=False)
    public_transit_accessible = models.BooleanField(default=True)
    
    # Weather considerations
    weather_dependent = models.BooleanField(
        default=False,
        help_text="Event may be cancelled due to weather"
    )
    rain_or_shine = models.BooleanField(default=False)
    
    # Additional info
    dress_code = models.CharField(
        max_length=100,
        blank=True,
        help_text="E.g., Casual, Business Casual, Formal"
    )
    what_to_bring = models.TextField(
        blank=True,
        help_text="What attendees should bring"
    )
    
    languages = models.JSONField(
        default=list,
        blank=True,
        help_text="Languages event will be conducted in"
    )
    
    # Status
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('postponed', 'Postponed'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed')
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='scheduled',
        db_index=True
    )
    
    cancellation_reason = models.TextField(blank=True)
    
    is_verified = models.BooleanField(
        default=False,
        help_text="Verified by admin/moderators"
    )
    
    # Stats
    view_count = models.IntegerField(default=0)
    bucket_list_count = models.IntegerField(
        default=0,
        help_text="How many times added to bucket lists"
    )
    attendance_count = models.IntegerField(
        default=0,
        help_text="How many users marked as attending"
    )
    interested_count = models.IntegerField(
        default=0,
        help_text="How many users marked as interested"
    )
    
    average_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(5)]
    )
    review_count = models.IntegerField(default=0)
    
    # SEO
    meta_description = models.CharField(max_length=160, blank=True)
    
    class Meta:
        db_table = 'events'
        ordering = ['start_date', 'start_time', 'name']
        indexes = [
            models.Index(fields=['start_date', 'status']),
            models.Index(fields=['city', 'category']),
            models.Index(fields=['is_featured', '-start_date']),
            models.Index(fields=['status', 'start_date']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(city__isnull=False) | (Q(country__isnull=False) & ~Q(location_text="")),
                name="event_has_city_or_typed_location",
            ),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.start_date})"
    
    @property
    def place_country(self):
        return self.city.country if self.city_id else self.country

    @property
    def place_name(self):
        """'City, Country' for display, whether or not the city is in the catalogue."""
        country = self.place_country
        town = self.city.name if self.city_id else self.location_text
        return ", ".join(part for part in (town, country.name if country else "") if part)

    @property
    def needs_city_link(self):
        return not self.city_id

    def is_visible_to(self, user):
        if user is not None and user.is_authenticated and (user.is_staff or user == self.created_by):
            return True
        return self.approval_status == ApprovalStatus.APPROVED

    def can_edit(self, user):
        """Creator until approved; staff always (same rule as activities)."""
        if user is None or not user.is_authenticated:
            return False
        if user.is_staff:
            return True
        return user == self.created_by and self.approval_status != ApprovalStatus.APPROVED

    def can_delete(self, user):
        return self.can_edit(user)

    @property
    def is_upcoming(self):
        """Check if event is in the future"""
        today = timezone.now().date()
        return self.start_date >= today and self.status == 'scheduled'
    
    @property
    def is_past(self):
        """Check if event has already occurred"""
        today = timezone.now().date()
        end = self.end_date if self.end_date else self.start_date
        return end < today or self.status == 'completed'
    
    @property
    def is_today(self):
        """Check if event is happening today"""
        today = timezone.now().date()
        if self.end_date:
            return self.start_date <= today <= self.end_date
        return self.start_date == today
    
    @property
    def duration_days(self):
        """Calculate event duration in days"""
        if self.end_date:
            return (self.end_date - self.start_date).days + 1
        return 1
    
    def save(self, *args, **kwargs):
        if not self.slug:
            from apps.core.utils import generate_unique_slug
            slug_base = f"{self.name}-{self.start_date.strftime('%Y-%m-%d')}"
            self.slug = generate_unique_slug(Event, slug_base, self.id)
        
        # Auto-set end_date if not provided
        if not self.end_date:
            self.end_date = self.start_date

        # Once linked to a catalogue city, the typed location is no longer needed.
        if self.city_id:
            self.country = None
            self.location_text = ""
        
        super().save(*args, **kwargs)


class EventTag(TimeStampedModel, SlugMixin):
    """Tags for categorizing and filtering events"""
    
    name = models.CharField(
        max_length=50,
        unique=True,
        help_text="E.g., family-friendly, outdoor, free, food, music"
    )
    description = models.CharField(max_length=200, blank=True)
    
    # Many-to-many with events
    events = models.ManyToManyField(
        Event,
        related_name='tags',
        blank=True
    )
    
    usage_count = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'event_tags'
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.slug:
            from apps.core.utils import generate_unique_slug
            self.slug = generate_unique_slug(EventTag, self.name, self.id)
        super().save(*args, **kwargs)


class EventPerformer(TimeStampedModel):
    """Performers/speakers/artists for events"""
    
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='performers'
    )
    
    name = models.CharField(max_length=200)
    
    PERFORMER_TYPES = [
        ('artist', 'Artist/Band'),
        ('speaker', 'Speaker'),
        ('dj', 'DJ'),
        ('performer', 'Performer'),
        ('comedian', 'Comedian'),
        ('host', 'Host/MC'),
        ('other', 'Other')
    ]
    performer_type = models.CharField(
        max_length=20,
        choices=PERFORMER_TYPES,
        default='artist'
    )
    
    bio = models.TextField(blank=True)
    website = models.URLField(blank=True)
    
    is_headliner = models.BooleanField(
        default=False,
        help_text="Featured/main performer"
    )
    
    performance_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Scheduled performance time"
    )
    
    display_order = models.IntegerField(
        default=0,
        help_text="Order in lineup"
    )
    
    class Meta:
        db_table = 'event_performers'
        ordering = ['event', 'display_order', 'name']
    
    def __str__(self):
        return f"{self.name} at {self.event.name}"


class EventSchedule(TimeStampedModel):
    """Detailed schedule for multi-session events"""
    
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='schedule_items'
    )
    
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    
    title = models.CharField(
        max_length=200,
        help_text="Session/activity title"
    )
    description = models.TextField(blank=True)
    
    location = models.CharField(
        max_length=200,
        blank=True,
        help_text="Specific location within venue (e.g., Room A, Main Stage)"
    )
    
    speaker_or_host = models.CharField(
        max_length=200,
        blank=True
    )
    
    is_break = models.BooleanField(
        default=False,
        help_text="Whether this is a break/intermission"
    )
    
    capacity = models.IntegerField(
        null=True,
        blank=True,
        help_text="Session capacity if limited"
    )
    
    requires_separate_ticket = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'event_schedules'
        ordering = ['event', 'date', 'start_time']
    
    def __str__(self):
        return f"{self.event.name} - {self.title} ({self.date} {self.start_time})"