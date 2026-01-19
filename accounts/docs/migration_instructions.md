# Migration Instructions for Role System Update

## Overview
This update implements:
- Username system (separate from email)
- Email OR username login
- Subscription tiers (free, plus, gold)
- Role request system (vendor, content provider)
- Role-specific profiles

## Files to Replace

### 1. Core Model Files (REPLACE COMPLETELY)
- `accounts/models.py` - Replace with new version
- `accounts/forms.py` - Replace with new version
- `accounts/views.py` - Replace with new version
- `accounts/urls.py` - Replace with new version
- `accounts/staff_urls.py` - Replace with new version

### 2. New Files (CREATE NEW)
- `accounts/backends.py` - New authentication backend
- `accounts/migrations/0009_role_system.py` - New migration
- `accounts/migrations/0010_migrate_existing_users.py` - Data migration

### 3. Settings Configuration

Add to your `settings.py`:

```python
# Authentication backends
AUTHENTICATION_BACKENDS = [
    'accounts.backends.EmailOrUsernameBackend',  # NEW - allows email or username login
    'django.contrib.auth.backends.ModelBackend',  # Keep as fallback
]
```

## Migration Steps

### Step 1: Backup Your Database
```bash
python manage.py dumpdata > backup_before_role_system.json
```

### Step 2: Replace Files
Copy all the updated files into your `accounts/` directory.

### Step 3: Run Migrations
```bash
# This will add new fields and tables
python manage.py migrate accounts 0009_role_system

# This will convert existing users from email usernames to proper usernames
python manage.py migrate accounts 0010_migrate_existing_users
```

### Step 4: Create Initial Groups
Run this in Django shell:
```bash
python manage.py shell
```

```python
from django.contrib.auth.models import Group

# Create the role groups
Group.objects.get_or_create(name='Vendors')
Group.objects.get_or_create(name='Content Providers')

print("Groups created successfully!")
```

### Step 5: Test Authentication
Try logging in with both:
- Your username
- Your email address

Both should work!

## What Changed for Existing Users

### Usernames
- **Before**: Users logged in with their email (email was the username)
- **After**: Users have proper usernames generated from their email
  - Example: `john.doe@example.com` becomes username `john_doe`
  - If collision, adds number: `john_doe1`, `john_doe2`, etc.

### Login
- Users can now log in with EITHER username or email
- Old login behavior still works (email login)
- New capability: username login

### Subscription System
- **Before**: `is_premium` boolean field
- **After**: `subscription_tier` field (free, plus, gold)
- `is_premium` still works as a property (returns True for plus/gold)
- Existing premium users migrated to 'gold' tier

## New Features Available

### For Users
1. **Profile URLs**: `yoursite.com/profile/username` instead of email
2. **Role Requests**: Can apply for vendor/content provider status
3. **Subscription Tiers**: Clear free/plus/gold membership levels

### For Admins
1. **Role Request Management**: 
   - View pending applications at `/staff/admin/role-requests/`
   - Approve/reject with reasons
2. **User Management**: 
   - See subscription tiers
   - See role capabilities
   - Manage role access via Groups

## Template Updates Needed

You'll need to update your templates to use the new fields:

### Before:
```django
{{ user.email }}  <!-- Don't show email publicly! -->
```

### After:
```django
{{ user.username }}  <!-- Show username publicly -->
{{ user.get_subscription_tier_display }}  <!-- Show tier -->
{% if user.is_vendor %}Vendor Badge{% endif %}
```

## New URL Patterns

Add these to your templates:

```django
{# Role request #}
<a href="{% url 'request_role' %}">Apply to become a vendor</a>

{# View role request status #}
<a href="{% url 'role_request_status' %}">My Applications</a>

{# Staff - review role requests #}
<a href="{% url 'staff:admin_role_requests' %}">Review Role Requests</a>
```

## Testing Checklist

- [ ] Existing users can log in with email
- [ ] Existing users can log in with new username
- [ ] New users can register with username
- [ ] Profile URLs work with username
- [ ] Role request form works
- [ ] Staff can approve/reject role requests
- [ ] Approved vendors get vendor group membership
- [ ] Subscription tiers display correctly

## Rollback Plan

If something goes wrong:

```bash
# Restore from backup
python manage.py loaddata backup_before_role_system.json

# Roll back migrations
python manage.py migrate accounts 0008_alter_user_options
```

## Support

If you encounter issues:
1. Check migration output for errors
2. Verify all files were copied correctly
3. Ensure `AUTHENTICATION_BACKENDS` is in settings.py
4. Check that Groups were created

## Next Steps After Migration

1. Create templates for:
   - `accounts/request_role.html` - Role request form
   - `accounts/role_request_status.html` - User's application status
   - `accounts/admin_role_requests.html` - Staff review page
   - `accounts/admin_role_request_detail.html` - Single request review

2. Update existing templates to:
   - Show username instead of email
   - Show vendor/content provider badges
   - Show subscription tier

3. Send announcement to users:
   - Explain new username system
   - Tell them they can log in with username OR email
   - Explain how to apply for vendor/content provider status
