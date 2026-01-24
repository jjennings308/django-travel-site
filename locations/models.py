# locations/models.py - UPDATED Country model section
# This shows only the changes needed to the Country model

from django.db import models
from core.models import TimeStampedModel, SlugMixin, FeaturedContentMixin
from django.core.validators import MinValueValidator, MaxValueValidator


class Country(TimeStampedModel, SlugMixin, FeaturedContentMixin):
    """Countries"""
    
    name = models.CharField(max_length=100, unique=True)
    iso_code = models.CharField(
        max_length=2,
        unique=True,
        help_text="ISO 3166-1 alpha-2 code"
    )
    iso3_code = models.CharField(
        max_length=3,
        unique=True,
        help_text="ISO 3166-1 alpha-3 code"
    )
    
    # Geographic data
    continent = models.CharField(
        max_length=50,
        choices=[
            ('Africa', 'Africa'),
            ('Antarctica', 'Antarctica'),
            ('Asia', 'Asia'),
            ('Europe', 'Europe'),
            ('North America', 'North America'),
            ('Oceania', 'Oceania'),
            ('South America', 'South America')
        ]
    )
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
    
    # Travel information
    currency_code = models.CharField(max_length=3, blank=True)
    currency_name = models.CharField(max_length=50, blank=True)
    phone_code = models.CharField(max_length=10, blank=True)
    
    # Metadata
    flag_emoji = models.CharField(
        max_length=10, 
        blank=True,
        help_text="Unicode flag emoji (e.g., 🇺🇸)"
    )
    description = models.TextField(blank=True)
    travel_tips = models.TextField(
        blank=True,
        help_text="General travel tips for this country"
    )
    
    # Visa information
    visa_required = models.BooleanField(
        default=True,
        help_text="General visa requirement info"
    )
    visa_info = models.TextField(
        blank=True,
        help_text="Visa requirements details"
    )
    
    # Stats (denormalized)
    city_count = models.IntegerField(default=0)
    poi_count = models.IntegerField(default=0)
    visitor_count = models.IntegerField(
        default=0,
        help_text="Number of users who visited"
    )
    
    class Meta:
        db_table = 'locations_countries'
        verbose_name_plural = 'Countries'
        ordering = ['name']
    
    def __str__(self):
        """Return country with flag emoji if available"""
        if self.flag_emoji:
            return f"{self.flag_emoji} {self.name}"
        return self.name
    
    @property
    def display_name(self):
        """Alternative property for getting name with flag"""
        return str(self)
    
    @property
    def flag(self):
        """Get flag emoji, generating from ISO code if needed"""
        if self.flag_emoji:
            return self.flag_emoji
        
        # Generate from ISO code if flag_emoji is empty
        if self.iso_code and len(self.iso_code) == 2:
            return ''.join(chr(0x1F1E6 + ord(c) - ord('A')) for c in self.iso_code.upper())
        
        return ''
    
    def save(self, *args, **kwargs):
        # Auto-generate flag emoji from ISO code if not set
        if not self.flag_emoji and self.iso_code and len(self.iso_code) == 2:
            self.flag_emoji = ''.join(
                chr(0x1F1E6 + ord(c) - ord('A')) 
                for c in self.iso_code.upper()
            )
        
        if not self.slug:
            from core.utils import generate_unique_slug
            self.slug = generate_unique_slug(Country, self.name, self.id)
        
        super().save(*args, **kwargs)


class Region(TimeStampedModel, SlugMixin):
    """States/Provinces/Regions within countries"""
    
    country = models.ForeignKey(
        Country,
        on_delete=models.CASCADE,
        related_name='regions'
    )
    
    name = models.CharField(max_length=100)
    code = models.CharField(
        max_length=10,
        blank=True,
        help_text="State/Province code (e.g., CA for California)"
    )
    
    # Geographic data
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
    
    description = models.TextField(blank=True)
    
    # Stats
    city_count = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'locations_regions'
        unique_together = [['country', 'name']]
        ordering = ['country', 'name']
    
    def __str__(self):
        return f"{self.name}, {self.country.name}"
    
    def save(self, *args, **kwargs):
        if not self.slug:
            from core.utils import generate_unique_slug
            self.slug = generate_unique_slug(
                Region,
                f"{self.name}-{self.country.iso_code}",
                self.id
            )
        super().save(*args, **kwargs)

class CapitalType(models.TextChoices):
    COUNTRY = "country", "Country capital"
    REGION = "region", "Region/State capital"
    BOTH = "both", "Country and Region capital"

class City(TimeStampedModel, SlugMixin, FeaturedContentMixin):
    """Cities within regions/countries"""
    
    country = models.ForeignKey(
        Country,
        on_delete=models.CASCADE,
        related_name='cities'
    )
    region = models.ForeignKey(
        Region,
        on_delete=models.SET_NULL,
        related_name='cities',
        null=True,
        blank=True
    )
    
    name = models.CharField(max_length=100)
    
    # Geographic data
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        help_text="City center coordinates"
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        help_text="City center coordinates"
    )
    timezone = models.CharField(
        max_length=50,
        blank=True,
        help_text="IANA timezone (e.g., America/New_York)"
    )
    elevation_m = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
        help_text="Elevation of the City in meters"
    )
    
    # Information
    description = models.TextField(blank=True)
    population = models.IntegerField(null=True, blank=True)
    
    # Travel information
    best_time_to_visit = models.CharField(
        max_length=200,
        blank=True,
        help_text="E.g., 'Spring (March-May) and Fall (Sept-Nov)'"
    )
    average_daily_budget = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Average daily budget in USD"
    )
    capital_type = models.CharField(
        max_length=10,
        choices=CapitalType.choices,
        blank=True,
        null=True,
        help_text="Capital level for this city"
    )
    is_capital = models.BooleanField(
        null=True,
        blank=True,
        default=False,
        help_text="Is this a capital city.  It can be the capital of the country or region/state"    
    )
    
    # Stats
    poi_count = models.IntegerField(default=0)
    visitor_count = models.IntegerField(default=0)
    average_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(5)]
    )
    review_count = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'locations_cities'
        verbose_name_plural = 'Cities'
        unique_together = [['country', 'name']]
        ordering = ['country', 'name']
    
    def __str__(self):
        if self.region:
            return f"{self.name}, {self.region.code}, {self.country.iso_code}"
        return f"{self.name}, {self.country.iso_code}"
    
    def save(self, *args, **kwargs):
        # Derive is_capital from capital_type
        self.is_capital = self.capital_type in {
            CapitalType.COUNTRY,
            CapitalType.REGION,
            CapitalType.BOTH,
        }

        if not self.slug:
            from core.utils import generate_unique_slug
            self.slug = generate_unique_slug(
                City,
                f"{self.name}-{self.country.iso_code}",
                self.id
            )
        super().save(*args, **kwargs)


class POI(TimeStampedModel, SlugMixin, FeaturedContentMixin):
    """Points of Interest (attractions, landmarks, etc.)"""
    
    city = models.ForeignKey(
        City,
        on_delete=models.CASCADE,
        related_name='pois'
    )
    
    name = models.CharField(max_length=200)
    
    POI_TYPES = [
        ('landmark', 'Landmark'),
        ('museum', 'Museum'),
        ('park', 'Park/Garden'),
        ('beach', 'Beach'),
        ('mountain', 'Mountain'),
        ('temple', 'Temple/Religious Site'),
        ('historical', 'Historical Site'),
        ('viewpoint', 'Viewpoint'),
        ('entertainment', 'Entertainment'),
        ('shopping', 'Shopping'),
        ('nightlife', 'Nightlife'),
        ('nature', 'Nature Reserve'),
        ('other', 'Other')
    ]
    poi_type = models.CharField(
        max_length=20,
        choices=POI_TYPES,
        default='landmark'
    )
    
    # Geographic data
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6
    )
    elevation_m = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
        help_text="Elevation of the POI in meters"
    )
    address = models.CharField(max_length=300, blank=True)
    
    # Information
    description = models.TextField(blank=True)
    website = models.URLField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    
    # Visiting information
    entry_fee = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Entry fee in local currency"
    )
    entry_fee_currency = models.CharField(max_length=3, blank=True)
    opening_hours = models.JSONField(
        default=dict,
        blank=True,
        help_text="Opening hours by day of week"
    )
    typical_duration = models.IntegerField(
        null=True,
        blank=True,
        help_text="Typical visit duration in minutes"
    )
    
    # Accessibility
    wheelchair_accessible = models.BooleanField(default=False)
    parking_available = models.BooleanField(default=False)
    
    # Stats
    visitor_count = models.IntegerField(default=0)
    average_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(5)]
    )
    review_count = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'locations_pois'
        verbose_name = 'POI'
        verbose_name_plural = 'POIs'
        ordering = ['city', 'name']
        indexes = [
            models.Index(fields=['poi_type']),
            models.Index(fields=['latitude', 'longitude']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.city.name})"
    
    def save(self, *args, **kwargs):
        if not self.slug:
            from core.utils import generate_unique_slug
            self.slug = generate_unique_slug(
                POI,
                f"{self.name}-{self.city.slug}",
                self.id
            )
        super().save(*args, **kwargs)