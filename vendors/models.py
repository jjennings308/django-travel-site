# vendors/models.py
from django.db import models
from core.models import TimeStampedModel, SlugMixin, FeaturedContentMixin
from django.core.validators import MinValueValidator, MaxValueValidator
from locations.models import City, POI


class VendorCategory(TimeStampedModel, SlugMixin):
    """Main vendor categories"""
    
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="E.g., Accommodation, Dining, Tours, Transportation"
    )
    description = models.TextField(blank=True)
    icon = models.CharField(
        max_length=50,
        blank=True,
        help_text="Icon name or emoji"
    )
    display_order = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'vendor_categories'
        verbose_name_plural = 'Vendor Categories'
        ordering = ['display_order', 'name']
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.slug:
            from core.utils import generate_unique_slug
            self.slug = generate_unique_slug(VendorCategory, self.name, self.id)
        super().save(*args, **kwargs)


class VendorType(TimeStampedModel, SlugMixin):
    """Specific vendor types within categories"""
    
    category = models.ForeignKey(
        VendorCategory,
        on_delete=models.CASCADE,
        related_name='types'
    )
    
    name = models.CharField(
        max_length=100,
        help_text="E.g., Hotel, Hostel, Restaurant, Tour Operator"
    )
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)
    
    class Meta:
        db_table = 'vendor_types'
        unique_together = [['category', 'name']]
        ordering = ['category', 'name']
    
    def __str__(self):
        return f"{self.category.name} - {self.name}"
    
    def save(self, *args, **kwargs):
        if not self.slug:
            from core.utils import generate_unique_slug
            self.slug = generate_unique_slug(
                VendorType,
                f"{self.category.name}-{self.name}",
                self.id
            )
        super().save(*args, **kwargs)


class Vendor(TimeStampedModel, SlugMixin, FeaturedContentMixin):
    """Individual vendors/businesses"""
    
    # Basic information
    name = models.CharField(max_length=200)
    vendor_type = models.ForeignKey(
        VendorType,
        on_delete=models.PROTECT,
        related_name='vendors'
    )
    
    # Location
    city = models.ForeignKey(
        City,
        on_delete=models.CASCADE,
        related_name='vendors'
    )
    poi = models.ForeignKey(
        POI,
        on_delete=models.SET_NULL,
        related_name='vendors',
        null=True,
        blank=True,
        help_text="If vendor is located at/near a specific POI"
    )
    
    address = models.CharField(max_length=300)
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
    
    # Contact information
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    booking_url = models.URLField(
        blank=True,
        help_text="Direct booking link"
    )
    
    # Social media
    instagram = models.CharField(max_length=100, blank=True)
    facebook = models.CharField(max_length=100, blank=True)
    
    # Description
    description = models.TextField(
        help_text="Detailed description of the vendor"
    )
    short_description = models.CharField(
        max_length=300,
        blank=True,
        help_text="Brief description for cards/lists"
    )
    
    # Pricing
    PRICE_RANGES = [
        ('budget', '$ - Budget'),
        ('moderate', '$$ - Moderate'),
        ('upscale', '$$$ - Upscale'),
        ('luxury', '$$$$ - Luxury')
    ]
    price_range = models.CharField(
        max_length=20,
        choices=PRICE_RANGES,
        default='moderate'
    )
    
    average_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Average price per night/meal/tour in local currency"
    )
    currency = models.CharField(
        max_length=3,
        default='USD',
        help_text="Currency code for prices"
    )
    
    # Operating information
    opening_hours = models.JSONField(
        default=dict,
        blank=True,
        help_text="Operating hours by day of week: {'monday': '9:00-17:00', ...}"
    )
    
    seasonal_closure = models.TextField(
        blank=True,
        help_text="Information about seasonal closures"
    )
    
    booking_required = models.BooleanField(
        default=False,
        help_text="Whether booking/reservation is required"
    )
    accepts_walk_ins = models.BooleanField(default=True)
    
    # Capacity (for accommodations/tours)
    capacity = models.IntegerField(
        null=True,
        blank=True,
        help_text="Max capacity (rooms for hotels, seats for tours, etc.)"
    )
    
    # Payment options
    accepts_credit_cards = models.BooleanField(default=True)
    accepts_cash = models.BooleanField(default=True)
    payment_methods = models.JSONField(
        default=list,
        blank=True,
        help_text="List of accepted payment methods"
    )
    
    # Languages spoken
    languages_spoken = models.JSONField(
        default=list,
        blank=True,
        help_text="List of language codes: ['en', 'es', 'fr']"
    )
    
    # Verification and status
    is_verified = models.BooleanField(
        default=False,
        help_text="Verified by admin/moderators"
    )
    verified_date = models.DateTimeField(null=True, blank=True)
    
    is_active = models.BooleanField(
        default=True,
        help_text="Whether vendor is currently operating"
    )
    
    is_partner = models.BooleanField(
        default=False,
        help_text="Official partner with special benefits"
    )
    
    claimed_by_owner = models.BooleanField(
        default=False,
        help_text="Whether business owner has claimed this listing"
    )
    
    # Stats (denormalized for performance)
    review_count = models.IntegerField(default=0)
    average_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(5)]
    )
    booking_count = models.IntegerField(
        default=0,
        help_text="Number of bookings through platform"
    )
    view_count = models.IntegerField(default=0)
    
    # SEO
    meta_description = models.CharField(
        max_length=160,
        blank=True,
        help_text="SEO meta description"
    )
    
    class Meta:
        db_table = 'vendors'
        ordering = ['-is_featured', '-average_rating', 'name']
        indexes = [
            models.Index(fields=['city', 'vendor_type']),
            models.Index(fields=['-average_rating']),
            models.Index(fields=['is_verified', 'is_active']),
            models.Index(fields=['latitude', 'longitude']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.city.name})"
    
    def save(self, *args, **kwargs):
        if not self.slug:
            from core.utils import generate_unique_slug
            self.slug = generate_unique_slug(
                Vendor,
                f"{self.name}-{self.city.slug}",
                self.id
            )
        super().save(*args, **kwargs)


class VendorAmenity(TimeStampedModel):
    """Amenities/features that vendors can offer"""
    
    AMENITY_CATEGORIES = [
        ('general', 'General'),
        ('accommodation', 'Accommodation'),
        ('dining', 'Dining'),
        ('accessibility', 'Accessibility'),
        ('technology', 'Technology'),
        ('recreation', 'Recreation'),
        ('services', 'Services')
    ]
    
    category = models.CharField(
        max_length=20,
        choices=AMENITY_CATEGORIES,
        default='general'
    )
    
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="E.g., WiFi, Pool, Parking, Pet Friendly"
    )
    description = models.CharField(max_length=200, blank=True)
    icon = models.CharField(max_length=50, blank=True)
    
    # Many-to-many with vendors
    vendors = models.ManyToManyField(
        Vendor,
        related_name='amenities',
        blank=True
    )
    
    is_premium = models.BooleanField(
        default=False,
        help_text="Premium amenity (highlighted in listings)"
    )
    
    display_order = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'vendor_amenities'
        verbose_name_plural = 'Vendor Amenities'
        ordering = ['category', 'display_order', 'name']
    
    def __str__(self):
        return f"{self.name} ({self.category})"


class VendorHours(TimeStampedModel):
    """Detailed operating hours for vendors (alternative to JSON field)"""
    
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.CASCADE,
        related_name='detailed_hours'
    )
    
    DAYS_OF_WEEK = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday')
    ]
    
    day_of_week = models.IntegerField(choices=DAYS_OF_WEEK)
    
    is_closed = models.BooleanField(default=False)
    
    opening_time = models.TimeField(null=True, blank=True)
    closing_time = models.TimeField(null=True, blank=True)
    
    # For split shifts (e.g., closes for lunch)
    second_opening_time = models.TimeField(null=True, blank=True)
    second_closing_time = models.TimeField(null=True, blank=True)
    
    notes = models.CharField(
        max_length=200,
        blank=True,
        help_text="E.g., 'Happy hour 5-7pm'"
    )
    
    class Meta:
        db_table = 'vendor_hours'
        unique_together = [['vendor', 'day_of_week']]
        ordering = ['vendor', 'day_of_week']
    
    def __str__(self):
        day_name = dict(self.DAYS_OF_WEEK)[self.day_of_week]
        if self.is_closed:
            return f"{self.vendor.name} - {day_name}: Closed"
        return f"{self.vendor.name} - {day_name}: {self.opening_time}-{self.closing_time}"


class VendorContact(TimeStampedModel):
    """Contact persons for vendors (for partnerships/business inquiries)"""
    
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.CASCADE,
        related_name='contacts'
    )
    
    name = models.CharField(max_length=100)
    title = models.CharField(
        max_length=100,
        blank=True,
        help_text="E.g., Manager, Owner, Marketing Director"
    )
    
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    
    is_primary = models.BooleanField(
        default=False,
        help_text="Primary contact for this vendor"
    )
    
    notes = models.TextField(blank=True)
    
    class Meta:
        db_table = 'vendor_contacts'
        ordering = ['-is_primary', 'name']
    
    def __str__(self):
        return f"{self.name} - {self.vendor.name}"