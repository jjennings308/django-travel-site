# Quick Reference Guide

## Installation Steps (TL;DR)

```bash
# 1. Backup
python manage.py dumpdata > backup.json

# 2. Copy files to accounts/ directory
# - Replace: models.py, forms.py, views.py, urls.py, staff_urls.py, admin.py
# - Add new: backends.py
# - Add new migrations: 0009_role_system.py, 0010_migrate_existing_users.py

# 3. Update settings.py
# Add: AUTHENTICATION_BACKENDS = ['accounts.backends.EmailOrUsernameBackend', ...]

# 4. Migrate
python manage.py migrate

# 5. Create groups
python manage.py shell
>>> from django.contrib.auth.models import Group
>>> Group.objects.get_or_create(name='Vendors')
>>> Group.objects.get_or_create(name='Content Providers')
>>> exit()

# 6. Test!
```

## Common Code Patterns

### Check User Capabilities
```python
# Subscription
user.is_premium  # True if plus or gold tier
user.subscription_tier  # 'free', 'plus', or 'gold'

# Roles
user.is_vendor  # True if in Vendors group
user.is_content_provider  # True if in Content Providers group

# Access
user.can_access_vendor_dashboard  # vendor OR staff
user.can_access_content_dashboard  # content provider OR staff
```

### Query Users by Role
```python
# All vendors
User.objects.filter(groups__name='Vendors')

# All content providers
User.objects.filter(groups__name='Content Providers')

# Premium vendors
User.objects.filter(
    groups__name='Vendors'
).exclude(subscription_tier='free')
```

### Handle Role Requests
```python
# User applies
role_request = RoleRequest.objects.create(
    user=user,
    requested_role=RoleRequest.RequestedRole.VENDOR,
    business_description="..."
)

# Staff approves
role_request.approve(reviewed_by=staff_user)
# This automatically:
# - Adds user to Vendors group
# - Creates VendorProfile
# - Sets status to approved

# Staff rejects
role_request.reject(
    reviewed_by=staff_user,
    reason="Does not meet requirements"
)
```

### Upgrade Subscription
```python
from django.utils import timezone
from datetime import timedelta

user.subscription_tier = User.SubscriptionTier.GOLD
user.subscription_expires = timezone.now() + timedelta(days=365)
user.save()
```

## Template Snippets

### Show User Info
```django
{# Username (public) #}
<a href="{% url 'profile_view' user.username %}">@{{ user.username }}</a>

{# Subscription badge #}
{% if user.is_premium %}
    <span class="badge badge-gold">{{ user.get_subscription_tier_display }}</span>
{% endif %}

{# Role badges #}
{% if user.is_vendor %}
    <span class="badge badge-vendor">Verified Vendor</span>
{% endif %}
{% if user.is_content_provider %}
    <span class="badge badge-content">Content Provider</span>
{% endif %}
```

### Conditional Features
```django
{# Show vendor dashboard link #}
{% if user.can_access_vendor_dashboard %}
    <a href="{% url 'vendor:dashboard' %}">Vendor Dashboard</a>
{% endif %}

{# Show apply button if not vendor #}
{% if not user.is_vendor %}
    <a href="{% url 'request_role' %}">Become a Vendor</a>
{% endif %}

{# Premium features #}
{% if user.subscription_tier == 'gold' %}
    <div class="premium-feature">
        {# Gold-only feature #}
    </div>
{% elif user.subscription_tier == 'plus' %}
    <div class="plus-feature">
        {# Plus-only feature #}
    </div>
{% endif %}
```

### Login Form
```django
{# User can enter either username or email #}
<form method="post" action="{% url 'login' %}">
    {% csrf_token %}
    <input type="text" name="username" placeholder="Username or Email">
    <input type="password" name="password" placeholder="Password">
    <button type="submit">Log In</button>
</form>
```

## URLs

### User-Facing
- `/accounts/register/` - Register new account
- `/accounts/login/` - Log in (username OR email)
- `/accounts/profile/` - Own profile
- `/accounts/profile/username/` - View user's profile
- `/accounts/profile/edit/` - Edit profile
- `/accounts/settings/` - Account settings
- `/accounts/request-role/` - Apply for vendor/content provider
- `/accounts/role-request-status/` - Check application status

### Staff-Only
- `/staff/admin/accounts/` - List all users
- `/staff/admin/accounts/<id>/` - User detail
- `/staff/admin/role-requests/` - Review role applications
- `/staff/admin/role-requests/<id>/` - Review specific request

## Model Fields

### User
```python
username  # CharField(30) - alphanumeric + underscore
email  # EmailField - unique
subscription_tier  # 'free', 'plus', 'gold'
subscription_expires  # DateTimeField - null for free
is_verified  # BooleanField - email verified
profile_visibility  # 'public', 'friends', 'private'
```

### RoleRequest
```python
user  # ForeignKey to User
requested_role  # 'vendor' or 'content_provider'
status  # 'pending', 'approved', 'rejected', 'revoked'
business_name  # CharField
business_description  # TextField
website  # URLField
business_license  # CharField
supporting_documents  # FileField
reviewed_by  # ForeignKey to User
reviewed_at  # DateTimeField
review_notes  # TextField (internal)
rejection_reason  # TextField (shown to user)
```

### VendorProfile
```python
user  # OneToOneField to User (primary key)
business_name  # CharField
business_description  # TextField
verification_status  # 'pending', 'verified', 'suspended'
total_listings  # IntegerField
average_rating  # DecimalField
total_bookings  # IntegerField
```

### ContentProviderProfile
```python
user  # OneToOneField to User (primary key)
portfolio_url  # URLField
bio  # TextField
specializations  # JSONField (list)
total_contributions  # IntegerField
content_rating  # DecimalField
```

## Groups

### Created by Migration
- `Vendors` - Users who can create/manage listings
- `Content Providers` - Users who can create content

### Checking Membership
```python
user.groups.filter(name='Vendors').exists()  # Boolean
user.is_vendor  # Property shortcut (same thing)
```

### Adding/Removing
```python
from django.contrib.auth.models import Group

# Add to group
vendor_group = Group.objects.get(name='Vendors')
user.groups.add(vendor_group)

# Remove from group
user.groups.remove(vendor_group)

# Or use the approve/reject methods on RoleRequest
```

## Admin Actions

### In Django Admin

**User Admin:**
- View/edit user details
- See subscription tier
- See if user is vendor/content provider
- Edit profile, travel preferences, settings inline

**RoleRequest Admin:**
- List all pending/approved/rejected requests
- View application details
- Approve by changing status to 'approved'
- Reject by changing status to 'rejected' and adding rejection_reason
- Auto-creates profiles and adds to groups on approval

## Common Tasks

### Grant Vendor Access Manually
```python
from django.contrib.auth.models import Group
from accounts.models import VendorProfile

# Add to group
vendor_group, _ = Group.objects.get_or_create(name='Vendors')
user.groups.add(vendor_group)

# Create profile
VendorProfile.objects.create(
    user=user,
    business_name="Their Business",
    business_description="Description here"
)
```

### Upgrade to Premium
```python
from django.utils import timezone
from datetime import timedelta

user.subscription_tier = User.SubscriptionTier.PLUS  # or GOLD
user.subscription_expires = timezone.now() + timedelta(days=365)
user.save()
```

### Check Pending Role Requests
```python
pending = RoleRequest.objects.filter(status='pending')
for req in pending:
    print(f"{req.user.username} wants to be {req.requested_role}")
```

### Revoke Vendor Access
```python
from django.contrib.auth.models import Group

# Remove from group
vendor_group = Group.objects.get(name='Vendors')
user.groups.remove(vendor_group)

# Optionally delete profile
if hasattr(user, 'vendor_profile'):
    user.vendor_profile.delete()
```

## Testing

### Test Username Login
```python
from django.test import Client
from accounts.models import User

client = Client()

# Create user
user = User.objects.create_user(
    username='testuser',
    email='test@example.com',
    password='testpass123'
)

# Login with username
response = client.post('/accounts/login/', {
    'username': 'testuser',
    'password': 'testpass123'
})
assert response.status_code == 302  # Redirect on success

# Login with email
client.logout()
response = client.post('/accounts/login/', {
    'username': 'test@example.com',  # Email in username field
    'password': 'testpass123'
})
assert response.status_code == 302  # Also works!
```

### Test Role Request
```python
from accounts.models import RoleRequest

# User applies
role_request = RoleRequest.objects.create(
    user=user,
    requested_role=RoleRequest.RequestedRole.VENDOR,
    business_description="Test business"
)

assert role_request.status == 'pending'
assert not user.is_vendor

# Approve
role_request.approve(reviewed_by=admin_user)

assert role_request.status == 'approved'
assert user.is_vendor
assert hasattr(user, 'vendor_profile')
```

## Troubleshooting

**Can't log in with email:**
- Check `AUTHENTICATION_BACKENDS` in settings.py
- Ensure `EmailOrUsernameBackend` is listed

**Username validation error:**
- Usernames can only contain: a-z, A-Z, 0-9, underscore
- Max 30 characters

**Role request not creating profile:**
- Check that Groups exist: `Group.objects.filter(name='Vendors')`
- Check approval was called: `role_request.approve(reviewed_by=user)`
- Check for errors in logs

**Migration fails:**
- Ensure all files are copied correctly
- Check for typos in migration files
- Try `python manage.py migrate --fake` if schema already correct

**Existing users can't log in:**
- Data migration should have converted usernames
- They can still use email to log in
- Check `user.username` doesn't contain @
