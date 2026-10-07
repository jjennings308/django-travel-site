# Accounts App Update - Implementation Summary

## What Changed

### 1. User Authentication System
**Before:**
- Username field contained the email address
- Users could only log in with email

**After:**
- Separate `username` field (alphanumeric + underscore only)
- Separate `email` field
- Users can log in with EITHER username OR email
- Profile URLs use username: `/profile/john_doe/` instead of `/profile/john@example.com/`

### 2. Subscription Tier System
**Before:**
- Simple `is_premium` boolean
- `premium_expires` datetime

**After:**
- `subscription_tier` field with choices: FREE, PLUS, GOLD
- `subscription_expires` datetime (null for free tier)
- `is_premium` property for backward compatibility (returns True for PLUS/GOLD)

### 3. Role System
**New Feature - Uses Django Groups:**
- Everyone starts as a Member (default user)
- Can apply for additional roles: Vendor, Content Provider
- Applications tracked in `RoleRequest` model
- Staff approve/reject applications
- Approved users added to Groups: "Vendors" or "Content Providers"
- Role-specific profiles created on approval

## Files Provided

### Complete Replacement Files
1. **models.py** - All models including new RoleRequest, VendorProfile, ContentProviderProfile
2. **forms.py** - Updated forms including RoleRequestForm
3. **views.py** - Updated views including role request handling
4. **urls.py** - Updated URL patterns
5. **staff_urls.py** - Staff URLs for role request management
6. **admin.py** - Updated Django admin configuration

### New Files
7. **backends.py** - Custom authentication backend for email/username login
8. **migrations/0009_role_system.py** - Schema migration
9. **migrations/0010_migrate_existing_users.py** - Data migration for existing users

### Documentation
10. **MIGRATION_INSTRUCTIONS.md** - Step-by-step migration guide
11. **IMPLEMENTATION_SUMMARY.md** - This file

## Architecture Decisions

### Why Groups Instead of a Role Field?

**Decision:** Use Django's built-in Groups for role capabilities

**Rationale:**
- User can have multiple capabilities (Member + Vendor)
- Leverages Django's permission system
- Easy to query: `user.groups.filter(name='Vendors').exists()`
- No need for custom role enforcement logic
- Groups can have permissions attached

### Subscription vs Role

**Subscription Tier** (FREE, PLUS, GOLD):
- Affects member benefits
- Example: Free = 5 trips, Plus = 20 trips, Gold = unlimited

**Roles** (Vendor, Content Provider):
- Affects what features you can access
- Requires approval
- Example: Vendors can list tours, Content Providers can upload guides

These are **independent**:
- A FREE member can be a Vendor
- A GOLD member might not be a Vendor
- Subscription affects member features, Roles affect professional features

## Database Schema Changes

### Modified Tables
```sql
-- users table
ALTER TABLE users ADD COLUMN subscription_tier VARCHAR(10) DEFAULT 'free';
ALTER TABLE users ADD COLUMN subscription_expires TIMESTAMP NULL;
-- username field gets regex validator constraint

-- Existing fields kept for compatibility:
-- is_premium (now a calculated property)
-- premium_expires (used by subscription_expires)
```

### New Tables
```sql
-- role_requests table
CREATE TABLE role_requests (
    id BIGINT PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    requested_role VARCHAR(20),  -- 'vendor' or 'content_provider'
    status VARCHAR(20),  -- 'pending', 'approved', 'rejected', 'revoked'
    business_name VARCHAR(200),
    business_description TEXT,
    website VARCHAR(200),
    business_license VARCHAR(100),
    supporting_documents VARCHAR(100),  -- file path
    reviewed_by_id BIGINT REFERENCES users(id),
    reviewed_at TIMESTAMP,
    review_notes TEXT,
    rejection_reason TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- vendor_profiles table
CREATE TABLE vendor_profiles (
    user_id BIGINT PRIMARY KEY REFERENCES users(id),
    business_name VARCHAR(200),
    business_description TEXT,
    business_license VARCHAR(100),
    website VARCHAR(200),
    verification_status VARCHAR(20),
    total_listings INTEGER DEFAULT 0,
    average_rating DECIMAL(3,2) DEFAULT 0.00,
    total_bookings INTEGER DEFAULT 0,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- content_provider_profiles table
CREATE TABLE content_provider_profiles (
    user_id BIGINT PRIMARY KEY REFERENCES users(id),
    portfolio_url VARCHAR(200),
    bio TEXT,
    specializations JSON,
    total_contributions INTEGER DEFAULT 0,
    content_rating DECIMAL(3,2) DEFAULT 0.00,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

## User Flow Examples

### New User Registration
1. User fills out form with username, email, password
2. Optionally checks "I want to become a vendor"
3. Account created as FREE member
4. If vendor checked, basic RoleRequest created (status: pending)
5. Email verification sent
6. User verifies email
7. User can complete vendor application with details
8. Staff reviews and approves
9. User added to Vendors group
10. VendorProfile created
11. User can now access vendor dashboard

### Existing User Gets Username
1. Migration runs
2. User's email username "john@example.com" converted to "john"
3. If "john" taken, becomes "john1", "john2", etc.
4. User can still log in with email (backward compatible)
5. User can now also log in with username
6. Profile URL changes from `/profile/john@example.com/` to `/profile/john/`

### Subscription Upgrade
```python
user.subscription_tier = User.SubscriptionTier.GOLD
user.subscription_expires = timezone.now() + timedelta(days=365)
user.save()

# Now:
user.is_premium  # True
user.get_subscription_tier_display()  # "Gold Member"
```

### Role Application
1. User clicks "Become a Vendor"
2. Fills out RoleRequestForm:
   - Business name
   - Description
   - Website
   - Business license (optional)
   - Supporting documents (optional)
3. RoleRequest created with status='pending'
4. Staff sees request in admin or staff dashboard
5. Staff reviews and either:
   - **Approves**: User added to Vendors group, VendorProfile created
   - **Rejects**: Rejection reason saved and user notified
6. User can check status at `/accounts/role-request-status/`

## Key Properties and Methods

### User Model
```python
user.username  # Unique username (not email)
user.email  # Unique email
user.subscription_tier  # 'free', 'plus', or 'gold'
user.is_premium  # Property: True if plus/gold and not expired
user.is_vendor  # Property: True if in Vendors group
user.is_content_provider  # Property: True if in Content Providers group
user.can_access_vendor_dashboard  # Property
user.can_access_content_dashboard  # Property
```

### RoleRequest Model
```python
role_request.approve(reviewed_by=staff_user)  # Grants role
role_request.reject(reviewed_by=staff_user, reason="...")  # Rejects
```

## Template Usage

### Display User Info
```django
{# Public profile - show username, not email #}
<h1>@{{ user.username }}</h1>

{# Show subscription tier #}
<span class="badge">{{ user.get_subscription_tier_display }}</span>

{# Show roles #}
{% if user.is_vendor %}
    <span class="badge badge-vendor">Vendor</span>
{% endif %}
{% if user.is_content_provider %}
    <span class="badge badge-content">Content Provider</span>
{% endif %}
```

### Role-Based Features
```django
{% if user.can_access_vendor_dashboard %}
    <a href="{% url 'vendor:dashboard' %}">Vendor Dashboard</a>
{% endif %}

{% if not user.is_vendor %}
    <a href="{% url 'request_role' %}">Become a Vendor</a>
{% endif %}
```

## Admin Interface

### User Admin
- List display includes username, email, subscription tier, roles
- Can see if user is vendor/content provider
- Inline editors for Profile, TravelPreferences, AccountSettings

### Role Request Admin
- List pending/approved/rejected requests
- Can approve/reject from admin
- Auto-creates role profiles on approval
- Tracks who reviewed and when

## API/Property Reference

### Checking Capabilities
```python
# Subscription checks
if user.is_premium:
    # User has paid subscription
    
if user.subscription_tier == User.SubscriptionTier.GOLD:
    # User has gold tier specifically

# Role checks
if user.is_vendor:
    # User has vendor capabilities
    
if user.can_access_vendor_dashboard:
    # User can access vendor features (vendor OR staff)

# Multiple roles
if user.is_vendor and user.is_content_provider:
    # User has both capabilities
```

### Querying Users
```python
# Get all vendors
vendors = User.objects.filter(groups__name='Vendors')

# Get all premium users
premium_users = User.objects.exclude(subscription_tier='free')

# Get premium vendors
premium_vendors = User.objects.filter(
    groups__name='Vendors'
).exclude(subscription_tier='free')

# Get pending role requests
pending = RoleRequest.objects.filter(status='pending')
```

## Settings Required

Add to `settings.py`:

```python
AUTHENTICATION_BACKENDS = [
    'accounts.backends.EmailOrUsernameBackend',  # Custom - email or username
    'django.contrib.auth.backends.ModelBackend',  # Fallback
]
```

## Migration Checklist

- [ ] Backup database
- [ ] Replace model files
- [ ] Add new files
- [ ] Update settings.py
- [ ] Run migrations
- [ ] Create Groups (Vendors, Content Providers)
- [ ] Test login with email
- [ ] Test login with username
- [ ] Test role request flow
- [ ] Update templates to show username
- [ ] Update templates for role badges

## Future Enhancements

Possible additions:
1. Email notifications when role request is approved/rejected
2. Vendor dashboard with stats
3. Content provider dashboard
4. Subscription payment integration
5. Role-specific permissions (beyond just access)
6. Multiple subscription tiers with different features
7. Trial periods for paid tiers
8. Role request history/analytics

## Backward Compatibility

✅ **Preserved:**
- `user.is_premium` still works (as property)
- Email login still works
- Existing profile data unchanged
- All existing relationships intact

✅ **Enhanced:**
- Can now also log in with username
- Premium users migrated to appropriate tier
- Email usernames converted to proper usernames

⚠️ **Changed:**
- Profile URLs now use username (redirect old URLs if needed)
- `user.username` no longer contains email
