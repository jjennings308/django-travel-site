"""Who is on a trip, and the rules for changing it (site roadmap R1).

Editors (the ``invite`` capability) run the People page: invite someone, change a role, remove
someone. Two rules hold everywhere, and the page and its tests both go through this module:

* nobody grants or sets a role above their own (staff count as editors);
* nobody demotes or removes the trip's creator.

Anyone may remove themselves (leave the trip), except the creator.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import TRIP_ROLE_RANK, Traveler, TripGrant, TripInvite, TripRole

log = logging.getLogger(__name__)

INVITES_PER_DAY = 20  # invite emails sent or resent per trip in any 24 hours


def rank(role):
    return TRIP_ROLE_RANK.get(role, -1) if role else -1


def actor_role(trip, user):
    """The role ``user`` acts with on this trip: their grant's, or editor for staff."""
    if user.is_staff or user.is_superuser:
        return TripRole.EDITOR
    return trip.grants.filter(user=user).values_list("role", flat=True).first()


def roles_up_to(role):
    """[(value, label)] of the roles someone acting as ``role`` may hand out."""
    return [(value, label) for value, label in TripRole.choices if rank(value) <= rank(role)]


def is_creator(trip, user_id):
    return trip.created_by_id is not None and trip.created_by_id == user_id


def can_set(trip, actor_role_value, grant, new_role):
    """May someone acting as ``actor_role_value`` set ``grant`` to ``new_role``?"""
    if new_role not in TripRole.values or is_creator(trip, grant.user_id):
        return False
    return rank(new_role) <= rank(actor_role_value) and rank(grant.role) <= rank(actor_role_value)


def can_remove(trip, actor, actor_role_value, grant):
    if is_creator(trip, grant.user_id):
        return False
    if grant.user_id == actor.pk:
        return True  # leaving
    return rank(actor_role_value) >= rank(TripRole.EDITOR) and rank(grant.role) <= rank(actor_role_value)


def give_at_least(trip, user, role, granted_by, quiet=False):
    """Give ``user`` ``role`` on ``trip``, or raise their lower role to it; never lowers one.

    Returns ``(grant, changed)``. A new grant sends the "You were added" notification
    (``signals.tell_new_grantee``) unless ``quiet`` — accepting an invite is the person's own act.
    """
    grant = TripGrant.objects.filter(trip=trip, user=user).first()
    if grant is None:
        grant = TripGrant(trip=trip, user=user, role=role, granted_by=granted_by)
        grant._quiet = quiet
        grant.save()
        return grant, True
    if rank(grant.role) < rank(role):
        grant.role = role
        grant.save(update_fields=["role"])
        return grant, True
    return grant, False


def account_for(email):
    """The active account with this email, if any (never shown to the inviter as such)."""
    return get_user_model().objects.filter(email__iexact=email.strip(), is_active=True).first()


def sent_today(trip):
    return trip.invites.filter(sent_at__gt=timezone.now() - timedelta(hours=24)).count()


def invite_url(invite):
    return f"{settings.SITE_URL.rstrip('/')}{reverse('trips:invite_accept', args=[invite.token])}"


def send_invite(invite):
    """Email the link. Mail trouble is logged and reported as False, never raised."""
    inviter = invite.invited_by
    context = {"invite": invite, "trip": invite.trip, "url": invite_url(invite), "site_name": settings.SITE_NAME,
               "inviter": (inviter.get_full_name() or inviter.username) if inviter else settings.SITE_NAME}
    body = render_to_string("trips/emails/invite.txt", context)
    try:
        EmailMessage(subject=f"[{settings.SITE_NAME}] {context['inviter']} invited you to “{invite.trip.name}”",
                     body=body, from_email=settings.DEFAULT_FROM_EMAIL, to=[invite.email]).send()
        return True
    except Exception:  # noqa: BLE001 - the invite stays; the editor can copy its link instead
        log.exception("Could not email trip invite %s", invite.pk)
        return False


def invite(trip, email, role, by):
    """Invite ``email`` as ``role``. An existing account gets its grant at once (returns
    ``(None, grant)``); otherwise the open invite for that address is created or renewed and
    emailed (returns ``(invite, None)``). The caller checks the role and the daily limit."""
    email = email.strip().lower()
    user = account_for(email)
    if user is not None:
        grant, _changed = give_at_least(trip, user, role, by)
        return None, grant
    pending = trip.invites.filter(email=email, accepted_at=None, revoked_at=None).first()
    if pending is None:
        pending = TripInvite(trip=trip, email=email)
    else:
        pending.renew()
    pending.role, pending.invited_by = role, by
    pending.save()
    send_invite(pending)
    return pending, None


def accept(invite, user, travelling=True):
    """``user`` accepts ``invite`` (which must be open): grant or raise, mark it used, optionally
    put them on the trip's travellers, tell the inviter. Returns the grant."""
    from apps.notifications.services import notify

    with transaction.atomic():
        locked = TripInvite.objects.select_for_update().get(pk=invite.pk)
        if not locked.is_open:
            raise ValueError(locked.state)
        trip = locked.trip
        grant, _changed = give_at_least(trip, user, locked.role, locked.invited_by, quiet=True)
        locked.accepted_at, locked.accepted_by = timezone.now(), user
        locked.save(update_fields=["accepted_at", "accepted_by"])
        if travelling:
            traveler = Traveler.objects.filter(user=user).first()
            if traveler is not None:
                trip.travelers.add(traveler)
    if locked.invited_by_id and locked.invited_by_id != user.pk:
        name = user.get_full_name() or user.username
        notify(locked.invited_by, "trip_invite_accepted", f"{name} joined “{trip.name}”",
               f"{name} accepted your invitation to “{trip.name}” and can now see it as "
               f"{grant.get_role_display().lower()}.",
               reverse("trips:trip_people", args=[trip.pk]), obj=trip)
    return grant
