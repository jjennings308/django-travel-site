# accounts/view.py
import json

from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib import messages
from django.shortcuts import render, redirect
from django.urls import reverse
from django.conf import settings

from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .forms import AdminUserCreateForm, SignUpForm
from .models import UserPreferences

User = get_user_model()


def staff_required(view_func):
    return user_passes_test(lambda u: u.is_authenticated and u.is_staff)(view_func)


@staff_required
def user_add(request):
    if request.method == "POST":
        form = AdminUserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"User created: {user.email}")
            return redirect("user-add")
    else:
        form = AdminUserCreateForm()

    return render(request, "accounts/user_add.html", {"form": form})


def signup(request):
    if request.user.is_authenticated:
        return redirect("/")

    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()

            # Build activation link
            uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)

            # You can set SITE_URL in settings, e.g. "https://yourdomain.com"
            site_url = getattr(settings, "SITE_URL", "http://127.0.0.1:8000")
            activation_url = site_url + reverse("activate", args=[uidb64, token])

            subject = "Activate your account"
            message = (
                f"Hi {user.first_name or user.username},\n\n"
                f"Please activate your account by clicking this link:\n"
                f"{activation_url}\n\n"
                f"If you didn’t create this account, you can ignore this email."
            )

            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )

            messages.success(
                request,
                "Account created! Check your email for an activation link."
            )
            return redirect("login")
    else:
        form = SignUpForm()

    return render(request, "accounts/signup.html", {"form": form})


def activate(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user and default_token_generator.check_token(user, token):
        user.is_active = True
        user.is_verified = True
        user.save(update_fields=["is_active", "is_verified"])
        messages.success(request, "Email verified — you can now log in.")
        return redirect("login")

    messages.error(request, "Activation link is invalid or expired.")
    return redirect("signup")

@login_required
@require_POST
def set_timezone(request):
    """
    Receives {"timezone": "America/New_York"} and stores it on UserPreferences.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    tz = (payload.get("timezone") or "").strip()
    if not tz or len(tz) > 50:
        return JsonResponse({"ok": False, "error": "Invalid timezone"}, status=400)

    prefs, _ = UserPreferences.objects.get_or_create(user=request.user)

    # Only write when it actually changes
    if prefs.timezone != tz:
        prefs.timezone = tz
        prefs.save(update_fields=["timezone", "updated_at"])

    return JsonResponse({"ok": True, "timezone": prefs.timezone})