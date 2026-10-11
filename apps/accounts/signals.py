# accounts/signals.py
"""Signals other apps listen to. accounts (layer 1) may not import notifications
(layer 2), so it announces events and notifications reacts."""
from django.dispatch import Signal

# Sent by RoleRequest.approve() / reject(); kwargs: request (the RoleRequest), approved (bool).
role_request_decided = Signal()
