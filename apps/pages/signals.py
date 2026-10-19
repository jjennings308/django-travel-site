"""Signing in again cancels a pending account deletion (site roadmap R13; ``account_data``)."""
from django.contrib import messages
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from . import account_data


@receiver(user_logged_in, dispatch_uid="cancel_account_deletion_on_login")
def cancel_deletion_on_login(sender, request, user, **kwargs):
    if account_data.cancel(user) and request is not None:
        messages.success(request, "Welcome back. Your account will not be deleted.")
