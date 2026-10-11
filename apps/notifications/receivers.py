# notifications/receivers.py
"""Notifications for things announced by lower apps (connected in NotificationsConfig.ready)."""
from django.dispatch import receiver
from django.urls import reverse

from apps.accounts.signals import role_request_decided

from .services import notify


@receiver(role_request_decided, dispatch_uid="notify_role_request_decided")
def role_request_was_decided(sender, request, approved, **kwargs):
    role = request.get_requested_role_display()
    if approved:
        title = f"Your {role} request was approved"
        message = f"Your request to become a {role} was approved. The extra features are now on your account."
    else:
        title = f"Your {role} request wasn't approved"
        message = f"Your request to become a {role} wasn't approved."
        if request.rejection_reason:
            message += f"\n\nReason: {request.rejection_reason}"
    notify(request.user, "role_request_decided", title, message, reverse("pages:dashboard"), obj=request)
