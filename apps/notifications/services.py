# notifications/services.py
"""Create notifications: one row per person (the header bell / Notifications page)
plus an email, unless the person turned off "Email notifications" in Settings.

Callers name a *kind* (a NotificationType.name). Sending mail never raises: a
reviewer's approval must not fail because the SMTP server did.
"""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.db.models import Q
from django.utils import timezone

from .models import Notification, NotificationCategory, NotificationType

log = logging.getLogger(__name__)

KINDS = {
    "submission_reviewed": "Your submission was reviewed",
    "submission_received": "New submission to review",
    "role_request_decided": "Your role request was decided",
    "trip_access_granted": "You were added to a trip",
}
CATEGORY = "Activity on your account"


def notification_type(kind):
    """The NotificationType for ``kind`` (seeded by migration 0002; created if missing)."""
    category, _ = NotificationCategory.objects.get_or_create(name=CATEGORY)
    ntype, _ = NotificationType.objects.get_or_create(
        name=kind, defaults={"category": category, "display_name": KINDS.get(kind, kind), "default_email": True})
    return ntype


def wants_email(user):
    if not user.is_active or not user.email or user.email.endswith("@noemail.invalid"):
        return False
    account_settings = getattr(user, "settings", None)  # accounts.AccountSettings, may not exist yet
    return getattr(account_settings, "email_notifications", True) if account_settings is not None else True


def notify(user, kind, title, message, url="", obj=None):
    """Create one notification for ``user`` and email it when they want email. Returns it."""
    if user is None or not user.is_active:
        return None
    note = Notification(user=user, notification_type=notification_type(kind), title=title[:200], message=message,
                        action_url=url, channels=["in_app"])
    if obj is not None and obj.pk is not None:
        note.content_object = obj
    note.save()
    if wants_email(user):
        link = f"{settings.SITE_URL.rstrip('/')}{url}" if url.startswith("/") else url
        body = f"{message}\n\n{link}\n" if link else f"{message}\n"
        body += f"\n— {settings.SITE_NAME}\nYou can turn these emails off under Settings → Email notifications."
        try:
            EmailMessage(subject=f"[{settings.SITE_NAME}] {title}", body=body,
                         from_email=settings.DEFAULT_FROM_EMAIL, to=[user.email]).send()
            note.channels = ["in_app", "email"]
            note.email_sent, note.email_sent_at = True, timezone.now()
            note.save(update_fields=["channels", "email_sent", "email_sent_at"])
        except Exception:  # noqa: BLE001 - mail trouble must never break the action that notified
            log.exception("Could not email notification %s to %s", note.pk, user.pk)
    return note


def staff_recipients(exclude=None):
    """Active users who can reach the staff dashboard (User.can_access_staff)."""
    codename = "can_access_staff_dashboard"
    users = get_user_model().objects.filter(is_active=True).filter(
        Q(is_superuser=True)
        | Q(user_permissions__codename=codename, user_permissions__content_type__app_label="accounts")
        | Q(groups__permissions__codename=codename, groups__permissions__content_type__app_label="accounts")
    ).distinct()
    if exclude is not None:
        users = users.exclude(pk=exclude.pk)
    return users


def notify_staff(kind, title, message, url="", obj=None, exclude=None):
    return [notify(user, kind, title, message, url, obj) for user in staff_recipients(exclude)]
