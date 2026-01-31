# Approval System - Complete Implementation Guide

## Overview

The **Approval System** is a reusable Django app that provides a complete content moderation and approval workflow for any model in your project. Instead of creating custom approval logic for each feature (locations, reviews, events, photos, etc.), you use one unified system.

## Key Benefits

### 1. **Reusability**
- Add approval to any model with one mixin
- Same workflow across your entire site
- Consistent user experience

### 2. **Centralization**
- Single approval dashboard for all content types
- Unified review queue
- One place to manage all pending content

### 3. **Flexibility**
- Multiple status states (draft, pending, approved, rejected, changes requested)
- Priority levels (low, normal, high, urgent)
- Custom approval queues
- Automated rules

### 4. **Audit Trail**
- Complete history of all approval actions
- Track who did what and when
- Review notes and reasons

### 5. **Scalability**
- Bulk operations
- Auto-approval rules
- Queue assignment
- SLA tracking

## Installation

### Step 1: Add to INSTALLED_APPS

```python
# settings.py

INSTALLED_APPS = [
    # ...
    'approval_system',
    # ...
]
```

### Step 2: Run Migrations

```bash
python manage.py makemigrations approval_system
python manage.py migrate approval_system
```

### Step 3: Add to URLs

```python
# project/urls.py

urlpatterns = [
    # ...
    path('approval/', include('approval_system.urls')),
    # ...
]
```

### Step 4: Create Initial Data

```bash
python manage.py shell
```

```python
from approval_system.models import ApprovalQueue, ApprovalSettings
from django.contrib.contenttypes.models import ContentType

# Create settings
settings = ApprovalSettings.get_settings()

# Create a default queue
from locations.models import City, Country, POI

queue = ApprovalQueue.objects.create(
    name='Locations Review',
    slug='locations',
    description='Review user-submitted locations',
    status_filter='pending',
    color='#007bff',
    icon='📍'
)

# Add content types to queue
queue.content_types.add(
    ContentType.objects.get_for_model(Country),
    ContentType.objects.get_for_model(City),
    ContentType.objects.get_for_model(POI),
)
```

## Usage

### Adding Approval to a Model

Simply inherit from `Approvable`:

```python
from django.db import models
from approval_system.models import Approvable

class YourModel(Approvable):
    # Your fields
    title = models.CharField(max_length=200)
    content = models.TextField()
    
    # Approvable automatically adds:
    # - approval_status
    # - submitted_by
    # - submitted_at
    # - reviewed_by
    # - reviewed_at
    # - approval_priority
```

### Admin Integration

Use the `ApprovableAdminMixin` for automatic approval features:

```python
from django.contrib import admin
from approval_system.admin import ApprovableAdminMixin
from .models import YourModel

@admin.register(YourModel)
class YourModelAdmin(ApprovableAdminMixin, admin.ModelAdmin):
    list_display = ['title', 'created_at']
    # Mixin automatically adds:
    # - approval_status_badge (colored status)
    # - submitted_by
    # - reviewed_by
    # Plus bulk approve/reject/request changes actions
```

### In Views

```python
from approval_system.models import ApprovalStatus

# Show only approved content to users
public_items = YourModel.objects.filter(approval_status=ApprovalStatus.APPROVED)

# Submit new content
def submit_item(request):
    item = YourModel()
    # ... set fields
    item.submit_for_review(request.user)
    # Now item.approval_status = 'pending'
```

### Approval Actions

```python
# Approve
item.approve(reviewer=request.user, notes='Looks good!')

# Reject
item.reject(reviewer=request.user, notes='Inappropriate content')

# Request changes
item.request_changes(reviewer=request.user, notes='Please add more details')

# Check status
if item.is_public():
    # Show to users
    
if item.is_pending():
    # Show in review queue
```

## Features

### 1. Status Workflow

```
DRAFT → PENDING → APPROVED (public)
                → REJECTED (hidden)
                → CHANGES_REQUESTED (user can edit and resubmit)
```

- **DRAFT**: User is still working on it
- **PENDING**: Submitted for review
- **APPROVED**: Reviewed and made public
- **REJECTED**: Rejected by reviewer
- **CHANGES_REQUESTED**: Needs edits before approval
- **ARCHIVED**: Old content removed from circulation

### 2. Priority Levels

- **URGENT**: Needs immediate attention
- **HIGH**: Important, review soon
- **NORMAL**: Standard priority
- **LOW**: No rush

### 3. Approval Queues

Create custom queues to organize pending content:

```python
# Urgent queue - high priority items
urgent_queue = ApprovalQueue.objects.create(
    name='Urgent Review',
    slug='urgent',
    priority_filter='urgent',
    color='#dc3545',  # Red
)

# New users queue - items from new contributors
new_users_queue = ApprovalQueue.objects.create(
    name='New Contributors',
    slug='new-users',
    description='Review items from users with <5 approved items',
)
```

### 4. Approval Logs

Every action is logged automatically:

```python
# Get approval history for an item
history = item.get_approval_history()

for log in history:
    print(f"{log.performed_by} {log.action} on {log.created_at}")
    print(f"Notes: {log.notes}")
```

### 5. Auto-Approval Rules

Create rules for automatic approval:

```python
from approval_system.models import ApprovalRule
from django.contrib.contenttypes.models import ContentType

# Auto-approve if user has 10+ approved items
rule = ApprovalRule.objects.create(
    name='Trusted User Auto-Approve',
    content_type=ContentType.objects.get_for_model(YourModel),
    auto_approve=True,
    conditions={
        'user_approved_count_gte': 10,
        'has_image': True,
    }
)
```

### 6. Unified Dashboard

Access all pending content in one place:

- Visit `/approval/` to see the main dashboard
- View by queue: `/approval/queue/locations/`
- Review specific item: `/approval/review/<content_type_id>/<object_id>/`
- View stats: `/approval/stats/`

## Models

### Approvable (Abstract Model)

Fields added to your model:
- `approval_status` - Current status (draft/pending/approved/rejected/changes_requested/archived)
- `submitted_by` - User who submitted
- `submitted_at` - When submitted
- `reviewed_by` - Staff who reviewed
- `reviewed_at` - When reviewed
- `approval_priority` - Priority level

Methods:
- `is_public()` - Returns True if approved
- `is_pending()` - Returns True if pending review
- `is_draft()` - Returns True if draft
- `submit_for_review(user)` - Submit for review
- `approve(reviewer, notes)` - Approve
- `reject(reviewer, notes)` - Reject
- `request_changes(reviewer, notes)` - Request changes
- `archive(user, notes)` - Archive
- `get_approval_history()` - Get all log entries

### ApprovalLog

Tracks all approval actions:
- Who performed action
- What action (submitted/approved/rejected/etc.)
- When it happened
- Status transition (old → new)
- Notes/reason
- IP address (optional)
- Metadata (JSON for extra data)

### ApprovalQueue

Organize pending items:
- Name and description
- Content types included
- Status filter (what to show)
- Priority filter
- Assigned reviewers
- Display settings (color, icon)

### ApprovalRule

Automated approval rules:
- Conditions for auto-approval
- Auto-reject conditions
- Reviewer assignment
- Priority (rule evaluation order)

### ApprovalSettings

Global configuration:
- Notification preferences
- Auto-archive settings
- Review SLA
- Dashboard settings

## API Endpoints

### Get Pending Counts
```
GET /approval/api/pending-counts/
```

Response:
```json
{
  "locations": {
    "name": "Locations Review",
    "count": 45,
    "color": "#007bff"
  },
  "total": 45
}
```

### Get Review Stats
```
GET /approval/api/stats/
```

## Workflows

### User Submission Workflow

1. **User creates content**
   ```python
   city = City(name="Paris", ...)
   ```

2. **User submits for review**
   ```python
   city.submit_for_review(request.user)
   # Creates approval log
   # Sets status to PENDING
   # Records submitted_by and submitted_at
   ```

3. **User views their submissions**
   - Go to `/approval/my-submissions/`
   - See status of all submitted items
   - View reviewer notes if changes requested

### Staff Review Workflow

1. **Staff accesses dashboard**
   - Go to `/approval/`
   - See all pending items across all content types
   - Organized by queues

2. **Staff reviews item**
   - Click on item to see details
   - View full content
   - Check approval history
   - Read submission notes

3. **Staff takes action**
   - Approve: `item.approve(request.user, "Verified!")`
   - Reject: `item.reject(request.user, "Duplicate")`
   - Request changes: `item.request_changes(request.user, "Add photo")`

4. **User is notified**
   - Email/notification sent (if configured)
   - User sees status in their submissions

### Bulk Review Workflow

1. **Select multiple items** in admin or dashboard
2. **Choose bulk action**: Approve / Reject / Request Changes
3. **All selected items updated** with one click
4. **Logs created** for each action

## Advanced Features

### Custom Queues

Create specialized queues for different review workflows:

```python
# Photos queue
photos_queue = ApprovalQueue.objects.create(
    name='Photo Moderation',
    slug='photos',
    description='Review user-uploaded photos',
)
photos_queue.content_types.add(ContentType.objects.get_for_model(Photo))

# Add specific reviewers
from accounts.models import User
photo_moderators = User.objects.filter(groups__name='Photo Moderators')
photos_queue.reviewers.set(photo_moderators)
```

### Auto-Assignment

Automatically assign items to specific reviewers based on rules:

```python
rule = ApprovalRule.objects.create(
    name='Assign photos to photo team',
    content_type=ContentType.objects.get_for_model(Photo),
    assign_to_user=photo_team_lead,
    conditions={'media_type': 'photo'}
)
```

### Review SLA Tracking

Set expected review time:

```python
settings = ApprovalSettings.get_settings()
settings.review_sla_hours = 24  # 24 hour SLA
settings.save()

# Now dashboard will highlight items overdue for review
```

### Notifications

Configure when to send notifications:

```python
settings = ApprovalSettings.get_settings()
settings.notify_on_submission = True  # Alert reviewers
settings.notify_on_approval = True    # Alert submitter
settings.notify_on_rejection = True   # Alert submitter
settings.save()
```

## Querying Examples

```python
from approval_system.models import ApprovalStatus, ApprovalPriority

# Get all pending items
pending = YourModel.objects.filter(approval_status=ApprovalStatus.PENDING)

# Get approved items only (for public display)
public = YourModel.objects.filter(approval_status=ApprovalStatus.APPROVED)

# Get user's submissions
mine = YourModel.objects.filter(submitted_by=request.user)

# Get urgent items
urgent = YourModel.objects.filter(
    approval_status=ApprovalStatus.PENDING,
    approval_priority=ApprovalPriority.URGENT
)

# Get items needing changes
needs_work = YourModel.objects.filter(
    approval_status=ApprovalStatus.CHANGES_REQUESTED
)

# Get items reviewed by specific person
reviewed_by_john = YourModel.objects.filter(
    reviewed_by__username='john'
)

# Get items pending over 24 hours
from django.utils import timezone
from datetime import timedelta
overdue = YourModel.objects.filter(
    approval_status=ApprovalStatus.PENDING,
    submitted_at__lt=timezone.now() - timedelta(hours=24)
)
```

## Migration Guide

### From Custom Review System

If you already have a custom review system (like the location review system we built earlier):

1. **Keep existing data**
   ```bash
   # Your existing migrations stay
   # Don't delete them
   ```

2. **Create new field mapping**
   ```python
   # Create migration to map old fields to new
   from django.db import migrations

   def map_old_to_new(apps, schema_editor):
       Country = apps.get_model('locations', 'Country')
       for country in Country.objects.all():
           # Map old 'status' to new 'approval_status'
           country.approval_status = country.status
           # Map other fields...
           country.save()
   
   class Migration(migrations.Migration):
       dependencies = [...]
       operations = [
           migrations.RunPython(map_old_to_new),
       ]
   ```

3. **Remove old fields** (optional)
   - Once migration is complete
   - Remove duplicate fields
   - Update references

## Best Practices

### 1. Always Filter Public Content

```python
# GOOD: Only show approved
items = Item.objects.filter(approval_status=ApprovalStatus.APPROVED)

# BAD: Shows all statuses
items = Item.objects.all()
```

### 2. Use Helper Methods

```python
# GOOD: Clear and semantic
if item.is_public():
    display_to_users(item)

# Less clear
if item.approval_status == 'approved':
    display_to_users(item)
```

### 3. Provide Clear Review Notes

```python
# GOOD: Specific feedback
item.request_changes(
    reviewer=request.user,
    notes="Please add: 1) Photos, 2) Opening hours, 3) Contact info"
)

# BAD: Vague
item.request_changes(reviewer=request.user, notes="Incomplete")
```

### 4. Set Appropriate Priorities

```python
# User reports inappropriate content
reported_item.approval_priority = ApprovalPriority.URGENT
reported_item.save()

# Regular user submission
new_item.approval_priority = ApprovalPriority.NORMAL
```

### 5. Monitor Review Queue

```python
# Check for overdue items daily
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        settings = ApprovalSettings.get_settings()
        cutoff = timezone.now() - timedelta(hours=settings.review_sla_hours)
        
        overdue = City.objects.filter(
            approval_status=ApprovalStatus.PENDING,
            submitted_at__lt=cutoff
        ).count()
        
        if overdue > 0:
            # Send alert to admin
            send_sla_breach_alert(overdue)
```

## Security Considerations

### 1. Permission Checks

```python
from django.contrib.auth.decorators import permission_required

@permission_required('approval_system.can_review')
def review_item(request, item_id):
    # Only users with permission can review
    pass
```

### 2. IP Logging

```python
# Logs automatically record IP for security
# Useful for investigating suspicious activity
```

### 3. Approval Limits

```python
# Prevent abuse - limit submissions per user
from django.core.exceptions import ValidationError

def submit_item(request):
    # Check submission count
    today_count = Item.objects.filter(
        submitted_by=request.user,
        submitted_at__date=timezone.now().date()
    ).count()
    
    if today_count >= 10:
        raise ValidationError("Daily submission limit reached")
```

## Troubleshooting

### Issue: Items not showing in queue

**Check:**
- Queue has correct content_types added
- Queue status_filter matches item status
- Queue is_active = True

### Issue: Bulk actions not working

**Check:**
- User has staff permissions
- Items are actually selected
- Check browser console for JS errors

### Issue: No approval history

**Check:**
- Actions were performed through model methods (approve(), reject())
- Not direct field updates (those don't create logs)

## Examples Across Different Content Types

### Example 1: User Reviews

```python
# models.py
from approval_system.models import Approvable

class Review(Approvable):
    place = models.ForeignKey(Place, on_delete=models.CASCADE)
    rating = models.IntegerField()
    text = models.TextField()
    
# Use it
review = Review(place=place, rating=5, text="Great!")
review.submit_for_review(request.user)
```

### Example 2: Event Submissions

```python
class Event(Approvable):
    title = models.CharField(max_length=200)
    date = models.DateField()
    description = models.TextField()
    
# User submits event
event = Event(title="Concert", ...)
event.submit_for_review(request.user)

# Staff reviews
if event.date >= timezone.now():
    event.approve(staff_user, "Valid event")
else:
    event.reject(staff_user, "Event date in past")
```

### Example 3: Photo Uploads

```python
class Photo(Approvable):
    image = models.ImageField()
    caption = models.TextField()
    
    # Override to add custom checks
    def submit_for_review(self, user=None):
        # Auto-set priority based on user reputation
        if user and user.photo_set.filter(
            approval_status=ApprovalStatus.APPROVED
        ).count() < 5:
            self.approval_priority = ApprovalPriority.HIGH
        
        super().submit_for_review(user)
```

## Summary

The Approval System provides:

✅ **One system for all content types**
✅ **Consistent user experience**  
✅ **Complete audit trail**
✅ **Flexible workflow**
✅ **Bulk operations**
✅ **Auto-approval rules**
✅ **Custom queues**
✅ **Priority management**
✅ **SLA tracking**
✅ **Easy integration**

This replaces the need for separate review systems for locations, reviews, events, photos, and any other user-generated content.
