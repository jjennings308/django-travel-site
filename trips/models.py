# trips/models.py
from django.db import models
from core.models import TimeStampedModel, SlugMixin
from accounts.models import User
from locations.models import City, Country
from activities.models import Activity
from vendors.models import Vendor
from events.models import Event
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone


class Trip(TimeStampedModel, SlugMixin):
    """User's trip/itinerary"""
    
    # Ownership
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='trips'
    )
    
    # Basic information
    title = models.CharField(
        max_length=200,
        help_text="Trip name (e.g., 'Summer 2024 Europe Tour')"
    )
    description = models.TextField(
        blank=True,
        help_text="Overview of the trip"
    )
    
    # Dates
    start_date = models.DateField(db_index=True)
    end_date = models.DateField(db_index=True)
    
    # Destinations (denormalized for quick access)
    primary_destination = models.ForeignKey(
        City,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='primary_trips',
        help_text="Main destination"
    )
    
    countries = models.ManyToManyField(
        Country,
        blank=True,
        related_name='trips',
        help_text="Countries visited on this trip"
    )
    
    # Trip type
    TRIP_TYPES = [
        ('leisure', 'Leisure/Vacation'),
        ('adventure', 'Adventure'),
        ('business', 'Business'),
        ('volunteer', 'Volunteer'),
        ('pilgrimage', 'Pilgrimage'),
        ('education', 'Educational'),
        ('family', 'Family Visit'),
        ('honeymoon', 'Honeymoon'),
        ('solo', 'Solo Travel'),
        ('backpacking', 'Backpacking'),
        ('road_trip', 'Road Trip'),
        ('cruise', 'Cruise'),
        ('other', 'Other')
    ]
    trip_type = models.CharField(
        max_length=20,
        choices=TRIP_TYPES,
        default='leisure'
    )
    
    # Status
    STATUS_CHOICES = [
        ('idea', 'Idea'),
        ('planning', 'Planning'),
        ('booked', 'Booked'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='planning',
        db_index=True
    )
    
    # Budget
    estimated_budget = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Estimated total budget"
    )
    actual_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Actual total cost"
    )
    currency = models.CharField(max_length=3, default='USD')
    
    # Travelers
    traveler_count = models.IntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Total number of travelers"
    )
    
    # Sharing and collaboration
    PRIVACY_CHOICES = [
        ('private', 'Private'),
        ('friends', 'Friends Only'),
        ('public', 'Public')
    ]
    privacy = models.CharField(
        max_length=20,
        choices=PRIVACY_CHOICES,
        default='private'
    )
    
    is_template = models.BooleanField(
        default=False,
        help_text="Whether this trip can be used as a template by others"
    )
    
    allow_collaborators = models.BooleanField(
        default=False,
        help_text="Allow others to collaborate on trip planning"
    )
    
    # Packing and preparation
    packing_list = models.JSONField(
        default=list,
        blank=True,
        help_text="List of items to pack"
    )
    
    pre_trip_checklist = models.JSONField(
        default=list,
        blank=True,
        help_text="Tasks to complete before trip"
    )
    
    # Notes
    notes = models.TextField(
        blank=True,
        help_text="General trip notes"
    )
    
    # Post-trip
    overall_rating = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Overall trip rating (1-5)"
    )
    
    trip_summary = models.TextField(
        blank=True,
        help_text="Summary/reflection after trip"
    )
    
    highlights = models.TextField(
        blank=True,
        help_text="Trip highlights"
    )
    
    # Stats (denormalized)
    day_count = models.IntegerField(default=0)
    city_count = models.IntegerField(default=0)
    activity_count = models.IntegerField(default=0)
    booking_count = models.IntegerField(default=0)
    
    # Engagement
    view_count = models.IntegerField(default=0)
    like_count = models.IntegerField(default=0)
    clone_count = models.IntegerField(
        default=0,
        help_text="How many times copied as template"
    )
    
    class Meta:
        db_table = 'trips'
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['start_date', 'end_date']),
            models.Index(fields=['status', '-start_date']),
        ]
    
    def __str__(self):
        return f"{self.title} ({self.start_date} to {self.end_date})"
    
    @property
    def duration_days(self):
        """Calculate trip duration in days"""
        return (self.end_date - self.start_date).days + 1
    
    @property
    def is_upcoming(self):
        """Check if trip is in the future"""
        return self.start_date > timezone.now().date() and self.status != 'cancelled'
    
    @property
    def is_current(self):
        """Check if trip is currently happening"""
        today = timezone.now().date()
        return self.start_date <= today <= self.end_date and self.status == 'in_progress'
    
    @property
    def is_past(self):
        """Check if trip is in the past"""
        return self.end_date < timezone.now().date() or self.status == 'completed'
    
    @property
    def budget_vs_actual(self):
        """Compare budget to actual cost"""
        if self.estimated_budget and self.actual_cost:
            return self.actual_cost - self.estimated_budget
        return None
    
    def save(self, *args, **kwargs):
        # Calculate day count
        self.day_count = self.duration_days
        
        # Generate slug
        if not self.slug:
            from core.utils import generate_unique_slug
            slug_base = f"{self.title}-{self.start_date.strftime('%Y-%m')}"
            self.slug = generate_unique_slug(Trip, slug_base, self.id)
        
        super().save(*args, **kwargs)


class TripCollaborator(TimeStampedModel):
    """Users who can collaborate on trip planning"""
    
    trip = models.ForeignKey(
        Trip,
        on_delete=models.CASCADE,
        related_name='collaborators'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='collaborative_trips'
    )
    
    ROLE_CHOICES = [
        ('viewer', 'Viewer'),
        ('editor', 'Editor'),
        ('co_owner', 'Co-Owner')
    ]
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='viewer'
    )
    
    invited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='trip_invitations_sent'
    )
    
    invitation_accepted = models.BooleanField(default=False)
    invitation_date = models.DateTimeField(auto_now_add=True)
    accepted_date = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'trip_collaborators'
        unique_together = [['trip', 'user']]
        ordering = ['trip', '-role']
    
    def __str__(self):
        return f"{self.user.username} ({self.role}) on {self.trip.title}"


class TripDay(TimeStampedModel):
    """Individual days within a trip"""
    
    trip = models.ForeignKey(
        Trip,
        on_delete=models.CASCADE,
        related_name='days'
    )
    
    date = models.DateField(db_index=True)
    day_number = models.IntegerField(
        help_text="Day 1, Day 2, etc."
    )
    
    # Location for this day
    city = models.ForeignKey(
        City,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='trip_days'
    )
    
    # Accommodation
    accommodation = models.ForeignKey(
        Vendor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='trip_days',
        limit_choices_to={'vendor_type__category__name': 'Accommodation'}
    )
    
    # Planning
    title = models.CharField(
        max_length=200,
        blank=True,
        help_text="E.g., 'Exploring Old Town', 'Beach Day'"
    )
    notes = models.TextField(
        blank=True,
        help_text="Notes for this day"
    )
    
    # Budget for this day
    estimated_cost = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True
    )
    actual_cost = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True
    )
    
    # Weather (can be fetched from API)
    weather_forecast = models.JSONField(
        default=dict,
        blank=True,
        help_text="Weather data for this day"
    )
    
    class Meta:
        db_table = 'trip_days'
        unique_together = [['trip', 'date']]
        ordering = ['trip', 'date']
        indexes = [
            models.Index(fields=['trip', 'date']),
        ]
    
    def __str__(self):
        return f"{self.trip.title} - Day {self.day_number} ({self.date})"


class TripActivity(TimeStampedModel):
    """Activities/events scheduled during a trip day"""
    
    trip_day = models.ForeignKey(
        TripDay,
        on_delete=models.CASCADE,
        related_name='activities'
    )
    
    # Activity reference
    activity = models.ForeignKey(
        Activity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='trip_activities'
    )
    
    # Event reference
    event = models.ForeignKey(
        Event,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='trip_activities'
    )
    
    # Vendor (restaurant, tour operator, etc.)
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='trip_activities'
    )
    
    # Custom activity
    custom_title = models.CharField(
        max_length=200,
        blank=True,
        help_text="For activities not in catalog"
    )
    custom_description = models.TextField(blank=True)
    
    # Timing
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    duration_minutes = models.IntegerField(
        null=True,
        blank=True,
        help_text="Expected duration"
    )
    
    # Location
    location_name = models.CharField(max_length=200, blank=True)
    address = models.CharField(max_length=300, blank=True)
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
    
    # Booking/reservation
    booking_required = models.BooleanField(default=False)
    booking_reference = models.CharField(max_length=100, blank=True)
    booking_status = models.CharField(
        max_length=20,
        choices=[
            ('none', 'Not Required'),
            ('needed', 'Booking Needed'),
            ('pending', 'Pending'),
            ('confirmed', 'Confirmed'),
            ('cancelled', 'Cancelled')
        ],
        default='none'
    )
    
    # Cost
    cost = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True
    )
    
    # Status
    is_confirmed = models.BooleanField(default=False)
    is_completed = models.BooleanField(default=False)
    
    # Notes
    notes = models.TextField(blank=True)
    
    # Display order
    display_order = models.IntegerField(
        default=0,
        help_text="Order of activities in the day"
    )
    
    # Post-activity
    user_rating = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    review_notes = models.TextField(
        blank=True,
        help_text="Personal review after completing"
    )
    
    class Meta:
        db_table = 'trip_activities'
        verbose_name_plural = 'Trip Activities'
        ordering = ['trip_day', 'start_time', 'display_order']
    
    def __str__(self):
        title = self.title
        return f"{self.trip_day} - {title}"
    
    @property
    def title(self):
        """Get display title"""
        if self.custom_title:
            return self.custom_title
        elif self.activity:
            return self.activity.name
        elif self.event:
            return self.event.name
        elif self.vendor:
            return self.vendor.name
        return "Untitled Activity"


class TripBooking(TimeStampedModel):
    """Bookings and reservations for the trip"""
    
    trip = models.ForeignKey(
        Trip,
        on_delete=models.CASCADE,
        related_name='bookings'
    )
    
    BOOKING_TYPES = [
        ('flight', 'Flight'),
        ('accommodation', 'Accommodation'),
        ('car_rental', 'Car Rental'),
        ('train', 'Train'),
        ('bus', 'Bus'),
        ('tour', 'Tour/Activity'),
        ('restaurant', 'Restaurant'),
        ('event', 'Event Ticket'),
        ('other', 'Other')
    ]
    booking_type = models.CharField(
        max_length=20,
        choices=BOOKING_TYPES
    )
    
    # Vendor reference
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bookings'
    )
    
    # Details
    title = models.CharField(
        max_length=200,
        help_text="E.g., 'Flight to Paris', 'Hotel Booking'"
    )
    description = models.TextField(blank=True)
    
    # Dates
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    
    # Booking details
    confirmation_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Confirmation/reference number"
    )
    
    booking_url = models.URLField(
        blank=True,
        help_text="Link to booking confirmation"
    )
    
    # Cost
    cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Total cost"
    )
    currency = models.CharField(max_length=3, default='USD')
    
    payment_status = models.CharField(
        max_length=20,
        choices=[
            ('unpaid', 'Unpaid'),
            ('deposit', 'Deposit Paid'),
            ('paid', 'Fully Paid'),
            ('refunded', 'Refunded')
        ],
        default='unpaid'
    )
    
    # Status
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed')
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    
    # Cancellation
    cancellation_policy = models.TextField(blank=True)
    is_refundable = models.BooleanField(default=False)
    cancellation_deadline = models.DateTimeField(null=True, blank=True)
    
    # Contact
    contact_name = models.CharField(max_length=200, blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    contact_email = models.EmailField(blank=True)
    
    # Notes
    notes = models.TextField(blank=True)
    
    # Attachments (confirmation emails, tickets, etc.)
    attachment_urls = models.JSONField(
        default=list,
        blank=True,
        help_text="URLs to attached documents"
    )
    
    class Meta:
        db_table = 'trip_bookings'
        ordering = ['trip', 'start_date', 'start_time']
        indexes = [
            models.Index(fields=['trip', 'booking_type']),
            models.Index(fields=['start_date']),
        ]
    
    def __str__(self):
        return f"{self.trip.title} - {self.title}"


class TripExpense(TimeStampedModel):
    """Track actual expenses during the trip"""
    
    trip = models.ForeignKey(
        Trip,
        on_delete=models.CASCADE,
        related_name='expenses'
    )
    
    trip_day = models.ForeignKey(
        TripDay,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='expenses'
    )
    
    EXPENSE_CATEGORIES = [
        ('accommodation', 'Accommodation'),
        ('food', 'Food & Dining'),
        ('transportation', 'Transportation'),
        ('activities', 'Activities & Tours'),
        ('shopping', 'Shopping'),
        ('entertainment', 'Entertainment'),
        ('miscellaneous', 'Miscellaneous')
    ]
    category = models.CharField(
        max_length=20,
        choices=EXPENSE_CATEGORIES
    )
    
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    
    date = models.DateField()
    
    # Payment method
    payment_method = models.CharField(
        max_length=50,
        blank=True,
        help_text="Credit card, cash, etc."
    )
    
    # Receipt
    receipt_photo = models.ImageField(
        upload_to='receipts/%Y/%m/',
        null=True,
        blank=True
    )
    
    notes = models.TextField(blank=True)
    
    class Meta:
        db_table = 'trip_expenses'
        ordering = ['trip', 'date']
    
    def __str__(self):
        return f"{self.trip.title} - {self.description} ({self.amount} {self.currency})"