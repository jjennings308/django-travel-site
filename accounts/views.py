# accounts/views.py
import logging
import json

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.auth.tokens import default_token_generator
from django.conf import settings
from django.urls import reverse
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST

from .models import User, Profile, TravelPreferences, AccountSettings
from .forms import (
    UserRegistrationForm, 
    ProfileForm, 
    TravelPreferencesForm,
    AccountSettingsForm
)


logger = logging.getLogger(__name__)


# ============================================
# REGISTRATION & EMAIL VERIFICATION
# ============================================

def register(request):
    """Handle user registration"""
    if request.user.is_authenticated and not request.user.can_access_staff:
        return redirect('core:home')
    
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save(commit=False)
                    
                    # If staff is creating the user, activate immediately
                    if request.user.is_authenticated and request.user.can_access_staff:
                        user.is_active = True
                        user.is_verified = True
                    else:
                        user.is_active = False
                    
                    user.username = user.email
                    user.save()
                    
                    # Create related models
                    Profile.objects.create(user=user)
                    TravelPreferences.objects.create(user=user)
                    AccountSettings.objects.create(user=user)
                    
                    # Send verification email only if self-registering
                    if not (request.user.is_authenticated and request.user.can_access_staff):
                        send_verification_email(request, user)
                        messages.success(
                            request,
                            'Registration successful! Please check your email to verify your account.'
                        )
                        return redirect('registration_complete')
                    else:
                        messages.success(
                            request,
                            f'User {user.email} has been created successfully and is immediately active.'
                        )
                        return redirect('staff:admin_account_list')
                    
            except Exception as e:
                import traceback
                logger.error(f"Registration error for {form.cleaned_data.get('email')}: {str(e)}")
                logger.error(traceback.format_exc())
                messages.error(
                    request,
                    f'An error occurred during registration: {str(e)}'
                )
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = UserRegistrationForm()
    
    return render(request, 'accounts/register.html', {'form': form})


def send_verification_email(request, user):
    """Send email verification link to user"""
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    
    verification_link = request.build_absolute_uri(
        reverse('verify_email', kwargs={'uidb64': uid, 'token': token})
    )
    
    logger.warning("VERIFICATION_LINK=%s", verification_link)
    print("VERIFICATION_LINK=", verification_link)

    subject = 'Verify Your Email Address'
    
    text_message = f"""
Hi {user.first_name},

Thank you for registering! Please verify your email address by clicking the link below:

{verification_link}

This link will expire in 24 hours.

If you didn't create this account, you can safely ignore this email.

Thanks,
The Travel Site Team
"""
    
    try:
        html_message = render_to_string('accounts/emails/verify_email.html', {
            'user': user,
            'verification_link': verification_link,
        })
    except Exception as e:
        logger.warning(f"Could not load email template: {e}. Using plain text.")
        html_message = None
    
    send_mail(
        subject,
        text_message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
        html_message=html_message
    )


def verify_email(request, uidb64, token):
    """Verify user's email address"""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist) as e:
        logger.error(f"Email verification error - could not decode user: {e}")
        user = None
    
    if user is not None:
        if user.is_verified and user.is_active:
            messages.info(request, 'Your email is already verified! You can log in.')
            return redirect('login')
        
        if default_token_generator.check_token(user, token):
            user.is_active = True
            user.is_verified = True
            user.save()
            
            messages.success(request, 'Your email has been verified! You can now log in.')
            return redirect('login')
        else:
            logger.warning(f"Invalid token for user {user.email}")
            messages.error(request, 'The verification link is invalid or has expired.')
            return redirect('resend_verification')
    else:
        messages.error(request, 'The verification link is invalid or has expired.')
        return redirect('resend_verification')


def registration_complete(request):
    """Show registration complete page"""
    return render(request, 'accounts/registration_complete.html')


def resend_verification(request):
    """Resend verification email"""
    if request.method == 'POST':
        email = request.POST.get('email')
        try:
            user = User.objects.get(email=email, is_verified=False)
            send_verification_email(request, user)
            messages.success(request, 'Verification email has been resent. Please check your inbox.')
        except User.DoesNotExist:
            messages.error(request, 'No unverified account found with that email address.')
    
    return render(request, 'accounts/resend_verification.html')


# ============================================
# PROFILE & PREFERENCES MANAGEMENT
# ============================================

@login_required
def profile_view(request, username=None):
    """View a user's profile"""
    if username:
        profile_user = get_object_or_404(User, username=username)
    else:
        profile_user = request.user
    
    # Check privacy settings
    if profile_user != request.user:
        if profile_user.profile_visibility == 'private':
            messages.error(request, 'This profile is private.')
            return redirect('core:home')
    
    try:
        profile = profile_user.profile
    except Profile.DoesNotExist:
        profile = Profile.objects.create(user=profile_user)
    
    # Get travel preferences for display
    try:
        travel_prefs = profile_user.travel_preferences
    except TravelPreferences.DoesNotExist:
        travel_prefs = None
    
    context = {
        'profile_user': profile_user,
        'profile': profile,
        'travel_preferences': travel_prefs,
        'is_own_profile': profile_user == request.user,
    }
    
    return render(request, 'accounts/profile.html', context)


@login_required
def edit_profile(request):
    """Edit user profile"""
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        profile = Profile.objects.create(user=request.user)
    
    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile has been updated.')
            return redirect('profile')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ProfileForm(instance=profile)
    
    return render(request, 'accounts/edit_profile.html', {'form': form})


@login_required
def edit_travel_preferences(request):
    """Edit travel preferences (shown on profile)"""
    try:
        travel_prefs = request.user.travel_preferences
    except TravelPreferences.DoesNotExist:
        travel_prefs = TravelPreferences.objects.create(user=request.user)
    
    if request.method == 'POST':
        form = TravelPreferencesForm(request.POST, instance=travel_prefs)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your travel preferences have been updated.')
            return redirect('profile')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = TravelPreferencesForm(instance=travel_prefs)
    
    return render(request, 'accounts/edit_travel_preferences.html', {'form': form})


@login_required
def settings_view(request):
    """Edit account settings (notifications, regional, privacy)"""
    try:
        account_settings = request.user.settings
    except AccountSettings.DoesNotExist:
        account_settings = AccountSettings.objects.create(user=request.user)

    if request.method == 'POST':
        form = AccountSettingsForm(request.POST, instance=account_settings)
        if form.is_valid():
            settings_obj = form.save()

            # ✅ BELT & SUSPENDERS: keep cookie in sync with DB
            response = redirect('settings')
            response.set_cookie(
                "ui_theme",
                settings_obj.theme,
                max_age=60 * 60 * 24 * 365,
                samesite="Lax",
            )

            messages.success(request, 'Your settings have been updated.')
            return response
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = AccountSettingsForm(instance=account_settings)

    return render(request, 'accounts/settings.html', {'form': form})


# ============================================
# ADMIN ACCOUNT MANAGEMENT
# ============================================

def can_access_staff_dashboard(user):
     return user.is_authenticated and getattr(user, "can_access_staff", False)

@login_required
@user_passes_test(can_access_staff_dashboard)
def admin_account_detail(request, user_id):
    """Admin view to see detailed account information"""
    user = get_object_or_404(User, id=user_id)
    
    try:
        profile = user.profile
    except Profile.DoesNotExist:
        profile = None
        
    try:
        travel_prefs = user.travel_preferences
    except TravelPreferences.DoesNotExist:
        travel_prefs = None
    
    try:
        settings_obj = user.settings
    except AccountSettings.DoesNotExist:
        settings_obj = None
    
    context = {
        'account_user': user,
        'profile': profile,
        'travel_preferences': travel_prefs,
        'account_settings': settings_obj,
        'stats': {
            'date_joined': user.created_at,
            'last_login': user.last_login,
            'is_verified': user.is_verified,
            'is_premium': user.is_premium,
            'premium_expires': user.premium_expires,
            'is_active': user.is_active,
            'is_staff': user.is_staff,
        }
    }
    
    return render(request, 'accounts/admin_account_detail.html', context)


@login_required
@user_passes_test(can_access_staff_dashboard)
def admin_account_list(request):
    """Admin view to list all user accounts with search and filters"""
    users = User.objects.all().select_related('profile')
    
    search_query = request.GET.get('search', '')
    if search_query:
        users = users.filter(
            email__icontains=search_query
        ) | users.filter(
            first_name__icontains=search_query
        ) | users.filter(
            last_name__icontains=search_query
        )
    
    verified_filter = request.GET.get('verified', '')
    if verified_filter == 'yes':
        users = users.filter(is_verified=True)
    elif verified_filter == 'no':
        users = users.filter(is_verified=False)
    
    premium_filter = request.GET.get('premium', '')
    if premium_filter == 'yes':
        users = users.filter(is_premium=True)
    elif premium_filter == 'no':
        users = users.filter(is_premium=False)
    
    active_filter = request.GET.get('active', '')
    if active_filter == 'yes':
        users = users.filter(is_active=True)
    elif active_filter == 'no':
        users = users.filter(is_active=False)
    
    order_by = request.GET.get('order_by', '-created_at')
    users = users.order_by(order_by)
    
    context = {
        'users': users,
        'search_query': search_query,
        'verified_filter': verified_filter,
        'premium_filter': premium_filter,
        'active_filter': active_filter,
        'order_by': order_by,
    }
    
    return render(request, 'accounts/admin_account_list.html', context)


@login_required
@user_passes_test(can_access_staff_dashboard)
def admin_toggle_user_status(request, user_id):
    """Admin action to toggle user active status"""
    if request.method != 'POST':
        return HttpResponse('Method not allowed', status=405)
    
    user = get_object_or_404(User, id=user_id)
    action = request.POST.get('action')
    
    if action == 'activate':
        user.is_active = True
        messages.success(request, f'User {user.email} has been activated.')
    elif action == 'deactivate':
        user.is_active = False
        messages.success(request, f'User {user.email} has been deactivated.')
    elif action == 'verify':
        user.is_verified = True
        messages.success(request, f'User {user.email} has been verified.')
    elif action == 'unverify':
        user.is_verified = False
        messages.success(request, f'User {user.email} verification has been removed.')
    
    user.save()
    
    return redirect('admin_account_detail', user_id=user_id)


@require_POST
def set_theme(request):
    """Set UI theme preference"""
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "bad_json"}, status=400)

    theme = data.get("theme")
    if theme not in ("brand", "light", "dark"):
        return JsonResponse({"ok": False, "error": "bad_theme"}, status=400)

    resp = JsonResponse({"ok": True, "theme": theme})
    resp.set_cookie("ui_theme", theme, max_age=60 * 60 * 24 * 365)

    # Persist to AccountSettings if logged in
    if request.user.is_authenticated and hasattr(request.user, "settings"):
        settings = request.user.settings
        settings.theme = theme
        settings.save(update_fields=["theme"])

    return resp
