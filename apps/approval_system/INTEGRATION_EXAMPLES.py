# locations/models.py - EXAMPLE: How to integrate with approval_system

from django.db import models
from core.models import TimeStampedModel, SlugMixin, FeaturedContentMixin
from approval_system.models import Approvable  # Import the Approvable mixin
from django.core.validators import MinValueValidator, MaxValueValidator


# NEW: Use Approvable instead of creating custom ReviewableMixin
class Country(TimeStampedModel, SlugMixin, FeaturedContentMixin, Approvable):
    """Countries with built-in approval workflow"""
    
    name = models.CharField(max_length=100, unique=True)
    iso_code = models.CharField(max_length=2, unique=True, help_text="ISO 3166-1 alpha-2 code")
    iso3_code = models.CharField(max_length=3, unique=True, help_text="ISO 3166-1 alpha-3 code")
    
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
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    
    # Travel information
    currency_code = models.CharField(max_length=3, blank=True)
    currency_name = models.CharField(max_length=50, blank=True)
    phone_code = models.CharField(max_length=10, blank=True)
    
    # Metadata
    flag_emoji = models.CharField(max_length=10, blank=True, help_text="Unicode flag emoji (e.g., 🇺🇸)")
    description = models.TextField(blank=True)
    travel_tips = models.TextField(blank=True, help_text="General travel tips for this country")
    
    # Visa information
    visa_required = models.BooleanField(default=True, help_text="General visa requirement info")
    visa_info = models.TextField(blank=True, help_text="Visa requirements details")
    
    # Stats (denormalized)
    city_count = models.IntegerField(default=0)
    poi_count = models.IntegerField(default=0)
    visitor_count = models.IntegerField(default=0, help_text="Number of users who visited")
    
    # Featured media
    featured_media = models.ForeignKey(
        'media_app.Media',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='featured_for_country'
    )
    
    class Meta:
        db_table = 'locations_countries'
        verbose_name_plural = 'Countries'
        ordering = ['name']
    
    def __str__(self):
        if self.flag_emoji:
            return f"{self.flag_emoji} {self.name}"
        return self.name
    
    @property
    def flag(self):
        """Get flag emoji, generating from ISO code if needed"""
        if self.flag_emoji:
            return self.flag_emoji
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


# Similar pattern for City, POI, Region, etc.
class City(TimeStampedModel, SlugMixin, FeaturedContentMixin, Approvable):
    """Cities with built-in approval workflow"""
    
    country = models.ForeignKey(Country, on_delete=models.CASCADE, related_name='cities')
    region = models.ForeignKey('Region', on_delete=models.SET_NULL, related_name='cities', null=True, blank=True)
    
    name = models.CharField(max_length=100)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, help_text="City center coordinates")
    longitude = models.DecimalField(max_digits=9, decimal_places=6, help_text="City center coordinates")
    timezone = models.CharField(max_length=50, blank=True, help_text="IANA timezone")
    
    description = models.TextField(blank=True)
    population = models.IntegerField(null=True, blank=True)
    
    # Featured media
    featured_media = models.ForeignKey(
        'media_app.Media',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='featured_for_city'
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
        return f"{self.name}, {self.country.iso_code}"
    
    def save(self, *args, **kwargs):
        if not self.slug:
            from core.utils import generate_unique_slug
            self.slug = generate_unique_slug(City, f"{self.name}-{self.country.iso_code}", self.id)
        super().save(*args, **kwargs)


# =====================================================
# ADMIN INTEGRATION EXAMPLE
# =====================================================

# locations/admin.py - EXAMPLE: How to integrate admin

from django.contrib import admin
from approval_system.admin import ApprovableAdminMixin
from .models import Country, City


@admin.register(Country)
class CountryAdmin(ApprovableAdminMixin, admin.ModelAdmin):
    """
    Country admin with approval system integration.
    ApprovableAdminMixin automatically adds:
    - approval_status_badge in list view
    - Bulk approve/reject/request changes actions
    - Approval filters
    """
    
    list_display = ['name', 'iso_code', 'continent', 'city_count', 'poi_count']
    # ApprovableAdminMixin will add: approval_status_badge, submitted_by, reviewed_by
    
    list_filter = ['continent']
    # ApprovableAdminMixin will add: approval_status, approval_priority, submitted_at
    
    search_fields = ['name', 'iso_code', 'iso3_code']
    readonly_fields = ['city_count', 'poi_count', 'visitor_count']
    # ApprovableAdminMixin will add: submitted_by, submitted_at, reviewed_by, reviewed_at
    
    fieldsets = [
        ('Basic Information', {
            'fields': ('name', 'slug', 'iso_code', 'iso3_code', 'flag_emoji', 'continent', 'description')
        }),
        ('Geographic Data', {
            'fields': ('latitude', 'longitude'),
        }),
        ('Travel Information', {
            'fields': ('currency_code', 'currency_name', 'phone_code', 'travel_tips', 'visa_required', 'visa_info'),
            'classes': ('collapse',)
        }),
        ('Featured Media', {
            'fields': ('featured_media',),
        }),
        ('Statistics', {
            'fields': ('city_count', 'poi_count', 'visitor_count'),
            'classes': ('collapse',)
        }),
        ('Approval Info', {
            'fields': ('approval_status', 'approval_priority', 'submitted_by', 'submitted_at', 
                      'reviewed_by', 'reviewed_at'),
            'classes': ('collapse',)
        }),
    ]


@admin.register(City)
class CityAdmin(ApprovableAdminMixin, admin.ModelAdmin):
    """City admin with approval system integration"""
    
    list_display = ['name', 'country', 'population', 'average_rating']
    list_filter = ['country']
    search_fields = ['name', 'country__name']
    autocomplete_fields = ['country', 'region']
    
    fieldsets = [
        ('Basic Information', {
            'fields': ('country', 'region', 'name', 'slug', 'description', 'population')
        }),
        ('Geographic Data', {
            'fields': ('latitude', 'longitude', 'timezone'),
        }),
        ('Featured Media', {
            'fields': ('featured_media',),
        }),
        ('Statistics', {
            'fields': ('poi_count', 'visitor_count', 'average_rating', 'review_count'),
            'classes': ('collapse',)
        }),
        ('Approval Info', {
            'fields': ('approval_status', 'approval_priority', 'submitted_by', 'submitted_at',
                      'reviewed_by', 'reviewed_at'),
            'classes': ('collapse',)
        }),
    ]


# =====================================================
# VIEWS INTEGRATION EXAMPLE
# =====================================================

# locations/views.py - EXAMPLE: How to use in views

from django.shortcuts import render
from .models import City, Country
from approval_system.models import ApprovalStatus


def city_list(request):
    """Show only approved cities to public users"""
    
    # Filter by approved status
    cities = City.objects.filter(
        approval_status=ApprovalStatus.APPROVED
    ).select_related('country')
    
    # Or use the helper method
    # cities = City.objects.filter(approval_status=ApprovalStatus.APPROVED)
    
    return render(request, 'locations/city_list.html', {
        'cities': cities
    })


def submit_city(request):
    """Allow users to submit new cities"""
    
    if request.method == 'POST':
        # Create city from form data
        city = City()
        # ... populate fields from form
        
        # Submit for review
        city.submit_for_review(request.user)
        
        messages.success(request, 'City submitted for review!')
        return redirect('my_submissions')
    
    return render(request, 'locations/submit_city.html')


# =====================================================
# QUERYSET EXAMPLES
# =====================================================

# Get only public/approved content
approved_countries = Country.objects.filter(approval_status=ApprovalStatus.APPROVED)

# Get pending items
pending_cities = City.objects.filter(approval_status=ApprovalStatus.PENDING)

# Get user's submissions
my_submissions = Country.objects.filter(submitted_by=request.user)

# Get items needing review (for staff)
needs_review = City.objects.filter(
    approval_status__in=[ApprovalStatus.PENDING, ApprovalStatus.CHANGES_REQUESTED]
).order_by('-submitted_at')

# Get urgent items
urgent_items = City.objects.filter(
    approval_status=ApprovalStatus.PENDING,
    approval_priority=ApprovalPriority.URGENT
)
