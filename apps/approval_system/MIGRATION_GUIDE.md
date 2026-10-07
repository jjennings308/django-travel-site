# Migration Guide: From Location Review System to Unified Approval System

## Overview

This guide helps you migrate from the location-specific review system to the unified Approval System. The unified system is better because:

1. **Reusable** - Works for locations, reviews, events, photos, anything
2. **Centralized** - One dashboard for all pending content
3. **Maintainable** - Update logic in one place
4. **Scalable** - Easy to add approval to new models

## Migration Strategy

You have two options:

### Option A: Fresh Start (Recommended for New Projects)
- Use Approval System from the beginning
- Simpler, cleaner
- No data migration needed

### Option B: Gradual Migration (Recommended for Existing Projects)
- Keep existing location review system working
- Add Approval System for new features
- Gradually migrate locations when ready
- Both systems can coexist

## Step-by-Step Migration

### Phase 1: Install Approval System

1. **Add to INSTALLED_APPS**

```python
# settings.py
INSTALLED_APPS = [
    # ...
    'approval_system',
    # ...
]
```

2. **Run Migrations**

```bash
python manage.py makemigrations approval_system
python manage.py migrate approval_system
```

3. **Add URLs**

```python
# project/urls.py
urlpatterns = [
    # Keep existing
    path('locations/', include('locations.urls')),
    
    # Add new
    path('approval/', include('approval_system.urls')),
]
```

### Phase 2: Set Up Initial Configuration

```python
python manage.py shell
```

```python
from approval_system.models import ApprovalQueue, ApprovalSettings
from django.contrib.contenttypes.models import ContentType

# Create settings
settings = ApprovalSettings.get_settings()
settings.review_sla_hours = 48
settings.save()

# Create locations queue
from locations.models import City, Country, POI, Region

locations_queue = ApprovalQueue.objects.create(
    name='Locations',
    slug='locations',
    description='User-submitted locations',
    status_filter='pending',
    color='#007bff',
    icon='📍'
)

locations_queue.content_types.add(
    ContentType.objects.get_for_model(Country),
    ContentType.objects.get_for_model(Region),
    ContentType.objects.get_for_model(City),
    ContentType.objects.get_for_model(POI),
)
```

### Phase 3: Update Models (Coexistence Approach)

Keep old fields, add new mixin alongside:

```python
# locations/models.py
from approval_system.models import Approvable

class Country(TimeStampedModel, SlugMixin, FeaturedContentMixin, Approvable):
    # Keep existing fields temporarily
    status = models.CharField(...)  # OLD - keep for now
    submitted_by_old = models.ForeignKey(...)  # OLD - keep for now
    
    # Approvable adds new fields:
    # - approval_status
    # - submitted_by (from Approvable)
    # - etc.
    
    # Your other fields
    name = models.CharField(max_length=100)
    # ...
```

### Phase 4: Create Data Migration

Map old fields to new ones:

```python
# locations/migrations/0006_migrate_to_approval_system.py

from django.db import migrations

def migrate_statuses(apps, schema_editor):
    """Map old status field to new approval_status"""
    
    Country = apps.get_model('locations', 'Country')
    
    status_mapping = {
        'pending': 'pending',
        'approved': 'approved',
        'rejected': 'rejected',
        'needs_changes': 'changes_requested',
    }
    
    for country in Country.objects.all():
        # Map status
        if country.status in status_mapping:
            country.approval_status = status_mapping[country.status]
        
        # Map submitted_by if it exists
        if hasattr(country, 'submitted_by_old') and country.submitted_by_old:
            country.submitted_by = country.submitted_by_old
        
        # Map reviewed_by
        if hasattr(country, 'reviewed_by_old') and country.reviewed_by_old:
            country.reviewed_by = country.reviewed_by_old
        
        # Map timestamps
        if hasattr(country, 'reviewed_at_old'):
            country.reviewed_at = country.reviewed_at_old
        
        country.save()


def reverse_migrate(apps, schema_editor):
    """Reverse migration if needed"""
    Country = apps.get_model('locations', 'Country')
    
    for country in Country.objects.all():
        # Map back to old fields
        if country.approval_status == 'pending':
            country.status = 'pending'
        # ... etc
        country.save()


class Migration(migrations.Migration):
    dependencies = [
        ('locations', '0005_add_review_system_and_featured_media'),
        ('approval_system', '0001_initial'),
    ]
    
    operations = [
        migrations.RunPython(migrate_statuses, reverse_migrate),
    ]
```

### Phase 5: Update Admin

Replace location-specific admin with unified approach:

```python
# locations/admin.py

from django.contrib import admin
from approval_system.admin import ApprovableAdminMixin  # NEW
from .models import Country, City, POI, Region


@admin.register(Country)
class CountryAdmin(ApprovableAdminMixin, admin.ModelAdmin):
    # Remove old ReviewableMixin
    # ApprovableAdminMixin provides:
    # - approval_status_badge
    # - Bulk approve/reject actions
    # - Approval filters
    
    list_display = ['name', 'iso_code', 'continent']
    # Mixin adds: approval_status_badge, submitted_by, reviewed_by
    
    search_fields = ['name', 'iso_code']
    
    fieldsets = [
        ('Basic Information', {
            'fields': ('name', 'iso_code', 'continent', 'description')
        }),
        # ... other fieldsets
        ('Approval', {
            'fields': ('approval_status', 'approval_priority', 
                      'submitted_by', 'submitted_at',
                      'reviewed_by', 'reviewed_at'),
            'classes': ('collapse',)
        }),
    ]


# Same pattern for City, POI, Region
@admin.register(City)
class CityAdmin(ApprovableAdminMixin, admin.ModelAdmin):
    # ...


@admin.register(POI)
class POIAdmin(ApprovableAdminMixin, admin.ModelAdmin):
    # ...
```

### Phase 6: Update Views

Replace location-specific views with unified system:

```python
# locations/views.py

from approval_system.models import ApprovalStatus

# OLD: Custom review dashboard
# def review_dashboard(request):
#     ... custom code for locations only

# NEW: Use unified approval dashboard instead
# Users visit /approval/ for all pending content


# Update public views to use new field
def city_list(request):
    # OLD:
    # cities = City.objects.filter(status='approved')
    
    # NEW:
    cities = City.objects.filter(approval_status=ApprovalStatus.APPROVED)
    
    return render(request, 'locations/city_list.html', {'cities': cities})


# Update submission views
def submit_city(request):
    if request.method == 'POST':
        city = City()
        # ... populate from form
        
        # OLD:
        # city.status = 'pending'
        # city.submitted_by = request.user
        # city.save()
        
        # NEW:
        city.submit_for_review(request.user)
        # Automatically sets status, submitted_by, submitted_at, creates log
        
        messages.success(request, 'City submitted for review!')
        return redirect('approval_system:my_submissions')
    
    return render(request, 'locations/submit_city.html')


# User's submissions - now unified
def my_submissions(request):
    # Redirect to unified submissions page
    return redirect('approval_system:my_submissions')
```

### Phase 7: Clean Up Old Code (Optional)

Once migration is complete and tested:

1. **Remove old templates**
```bash
rm locations/templates/locations/review_dashboard.html
rm locations/templates/locations/review_location.html
# Keep using unified approval templates
```

2. **Remove old URLs**
```python
# locations/urls.py
# Remove old review URLs
# urlpatterns = [
#     path('review/', views.review_dashboard, name='review_dashboard'),
#     # ... other old review URLs
# ]

# Keep only public-facing URLs
urlpatterns = [
    path('countries/', views.country_list, name='country_list'),
    path('cities/', views.city_list, name='city_list'),
    # ...
]
```

3. **Remove old fields** (after confirming everything works)
```python
# Create a migration to remove old fields
# locations/migrations/0007_remove_old_review_fields.py

from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ('locations', '0006_migrate_to_approval_system'),
    ]
    
    operations = [
        migrations.RemoveField(model_name='country', name='status'),
        migrations.RemoveField(model_name='country', name='submitted_by_old'),
        # ... remove other old fields
    ]
```

## Comparison

### Before (Location-Specific)
```python
# Different review logic for each app
locations/
  models.py - ReviewableMixin, custom status
  views.py - review_dashboard, review_location
  admin.py - custom ReviewableMixin
  templates/locations/ - review templates

reviews/
  models.py - Different ReviewableMixin
  views.py - Different review_dashboard
  admin.py - Different admin mixins
  templates/reviews/ - Different review templates

# Problems:
- Duplicate code across apps
- Inconsistent workflows
- Multiple dashboards to check
- Hard to maintain
```

### After (Unified Approval System)
```python
# One system for everything
approval_system/
  models.py - Approvable (works for any model)
  views.py - Unified dashboard
  admin.py - ApprovableAdminMixin
  templates/ - One set of review templates

locations/models.py - class Country(Approvable)
reviews/models.py - class Review(Approvable)
events/models.py - class Event(Approvable)
photos/models.py - class Photo(Approvable)

# Benefits:
- One codebase to maintain
- Consistent workflow everywhere
- Single approval dashboard
- Easy to add to new models
```

## Testing Your Migration

### 1. Test Old Data

```python
# Verify status mapping worked
from locations.models import Country

# Check a country that was approved
country = Country.objects.get(name="United States")
assert country.approval_status == 'approved'
assert country.is_public() == True

# Check a country that was pending
pending_country = Country.objects.filter(approval_status='pending').first()
assert pending_country.is_pending() == True
```

### 2. Test New Submissions

```python
# Create new submission
city = City(name="Test City", country=usa, ...)
city.submit_for_review(test_user)

# Verify it works
assert city.approval_status == 'pending'
assert city.submitted_by == test_user
assert city.submitted_at is not None

# Check log was created
logs = city.get_approval_history()
assert logs.count() > 0
assert logs.first().action == 'submitted'
```

### 3. Test Review Actions

```python
# Test approval
city.approve(staff_user, "Looks good!")
assert city.approval_status == 'approved'
assert city.reviewed_by == staff_user

# Verify log
logs = city.get_approval_history()
approval_log = logs.filter(action='approved').first()
assert approval_log.notes == "Looks good!"
```

### 4. Test Dashboard

```bash
# Visit unified dashboard
http://localhost:8000/approval/

# Should show:
- All pending items across all models
- Organized by queue
- Color-coded statuses
- Action buttons
```

### 5. Test Queries

```python
# Public content only
public_cities = City.objects.filter(approval_status='approved')

# Pending review
pending = City.objects.filter(approval_status='pending')

# User's submissions
mine = City.objects.filter(submitted_by=request.user)

# All should work correctly
```

## Rollback Plan

If you need to rollback:

1. **Keep old fields** during migration (don't remove them)
2. **Run reverse migration**
```bash
python manage.py migrate locations 0005
```
3. **Switch URLs back**
```python
# Use old review URLs again
path('locations/review/', views.review_dashboard),
```
4. **Revert views** to use old fields
```python
cities = City.objects.filter(status='approved')  # old field
```

## Support

Common issues:

**Issue**: Both old and new dashboards showing
**Fix**: Update navigation to only show `/approval/`, remove old review links

**Issue**: Some items not showing in queue
**Fix**: Check queue content_types include all your models

**Issue**: Approval logs not created for old data
**Fix**: That's expected - logs are only created for new actions

**Issue**: Permissions error
**Fix**: Make sure staff users have approval_system permissions

## Conclusion

Benefits of migration:

✅ One system for all content types
✅ Unified dashboard
✅ Consistent user experience
✅ Easier maintenance
✅ Scalable to new features
✅ Complete audit trail
✅ Advanced features (queues, rules, SLA)

The migration can be done gradually, and both systems can coexist during transition.
