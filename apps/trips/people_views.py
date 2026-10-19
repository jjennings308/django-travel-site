"""The People page and invite links (site roadmap R1). The rules live in ``people.py``.

``trips:trip_people`` — everyone who can see the trip sees who is on it; editors (``invite``)
invite, change roles, remove, and resend or cancel open invites. Anyone but the creator may leave.
``trips:invite_accept`` — the link in an invite email: signed out, log in or create an account and
come back; signed in, **Join trip**. Expired, cancelled or used links say so and grant nothing.
"""
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from . import people
from .models import Trip, TripGrant, TripInvite, TripRole


class InviteForm(forms.Form):
    email = forms.EmailField(label="Email address", widget=forms.EmailInput(attrs={"autocomplete": "off"}))
    role = forms.ChoiceField(label="Role", choices=TripRole.choices, initial=TripRole.VIEWER)

    def __init__(self, *args, roles=None, **kwargs):
        super().__init__(*args, **kwargs)
        if roles is not None:
            self.fields["role"].choices = roles


def _people_context(request, trip, actor_role, can_invite, form=None):
    grants = list(trip.grants.select_related("user", "granted_by").order_by("granted_at", "pk"))
    roles = people.roles_up_to(actor_role) if can_invite else []
    for grant in grants:
        grant.is_creator = people.is_creator(trip, grant.user_id)
        grant.is_me = grant.user_id == request.user.pk
        grant.can_set = can_invite and people.can_set(trip, actor_role, grant, grant.role)
        grant.can_remove = people.can_remove(trip, request.user, actor_role, grant)
    invites = []
    if can_invite:
        invites = [i for i in trip.invites.filter(accepted_at=None, revoked_at=None).select_related("invited_by")]
        for invite in invites:
            invite.link = people.invite_url(invite)
    return {
        "trip": trip, "grants": grants, "invites": invites, "roles": roles, "can_invite": can_invite,
        "form": form or InviteForm(roles=roles), "limit": people.INVITES_PER_DAY,
    }


@login_required
def trip_people(request, pk):
    trip = get_object_or_404(Trip.objects.visible_to(request.user), pk=pk)
    caps = trip.capabilities_for(request.user)
    if "view" not in caps:
        raise PermissionDenied
    can_invite = "invite" in caps
    actor_role = people.actor_role(trip, request.user)
    if request.method != "POST":
        return render(request, "trips/trip_people.html", _people_context(request, trip, actor_role, can_invite))

    action = request.POST.get("action")
    back = redirect("trips:trip_people", pk=trip.pk)
    if action == "remove":
        grant = get_object_or_404(TripGrant, trip=trip, pk=request.POST.get("grant"))
        if not people.can_remove(trip, request.user, actor_role, grant):
            raise PermissionDenied
        leaving = grant.user_id == request.user.pk
        name = grant.user.get_full_name() or grant.user.username
        grant.delete()
        if leaving and not (request.user.is_staff or request.user.is_superuser):
            messages.success(request, f"You left “{trip.name}”.")
            return redirect("trips:trip_list")
        messages.success(request, f"{name} no longer has access to this trip.")
        return back
    if not can_invite:
        raise PermissionDenied

    if action == "invite":
        roles = people.roles_up_to(actor_role)
        form = InviteForm(request.POST, roles=roles)
        if not form.is_valid():
            return render(request, "trips/trip_people.html",
                          _people_context(request, trip, actor_role, can_invite, form), status=400)
        if people.sent_today(trip) >= people.INVITES_PER_DAY:
            messages.error(request, f"This trip has sent {people.INVITES_PER_DAY} invitations in the last day. "
                                    "Try again tomorrow.")
            return back
        email, role = form.cleaned_data["email"], form.cleaned_data["role"]
        people.invite(trip, email, role, request.user)
        # The same words either way, so the message never says whether the address has an account.
        messages.success(request, f"Invited {email.strip().lower()} as {TripRole(role).label.lower()}.")
        return back
    if action == "role":
        grant = get_object_or_404(TripGrant, trip=trip, pk=request.POST.get("grant"))
        role = request.POST.get("role")
        if not people.can_set(trip, actor_role, grant, role):
            raise PermissionDenied
        if grant.role != role:
            grant.role = role
            grant.save(update_fields=["role"])
            name = grant.user.get_full_name() or grant.user.username
            messages.success(request, f"{name} is now {TripRole(role).label.lower()}.")
        return back
    if action in ("resend", "cancel"):
        invite = get_object_or_404(TripInvite, trip=trip, pk=request.POST.get("invite"),
                                   accepted_at=None, revoked_at=None)
        if people.rank(invite.role) > people.rank(actor_role):
            raise PermissionDenied
        if action == "cancel":
            invite.revoked_at = timezone.now()
            invite.save(update_fields=["revoked_at"])
            messages.success(request, f"Cancelled the invitation to {invite.email}. Its link no longer works.")
            return back
        if people.sent_today(trip) >= people.INVITES_PER_DAY:
            messages.error(request, f"This trip has sent {people.INVITES_PER_DAY} invitations in the last day. "
                                    "Try again tomorrow.")
            return back
        invite.renew()
        invite.invited_by = request.user
        invite.save()
        people.send_invite(invite)
        messages.success(request, f"Sent the invitation to {invite.email} again, with a new link.")
        return back
    return back


def invite_accept(request, token):
    """The link in an invite email. Never says whether an address has an account."""
    invite = (TripInvite.objects.select_related("trip", "invited_by")
              .filter(token=token).filter(Q(trip__deleted_at__isnull=True)).first())
    if invite is None:
        return render(request, "trips/invite_accept.html", {"state": "missing"}, status=404)
    trip = invite.trip
    inviter = invite.invited_by
    context = {"invite": invite, "trip": trip, "state": invite.state,
               "inviter": (inviter.get_full_name() or inviter.username) if inviter else "Someone"}
    if not invite.is_open:
        return render(request, "trips/invite_accept.html", context, status=410)
    if not request.user.is_authenticated:
        # While sign-up is invite-only, holding an open invite lets this visitor register for a
        # day (accounts reads the same session key; site roadmap R14).
        import time
        request.session["signup_allowed_until"] = time.time() + 86400
        here = request.get_full_path()
        context["login_url"] = f"{reverse('login')}?{urlencode({'next': here})}"
        context["register_url"] = f"{reverse('register')}?{urlencode({'next': here, 'email': invite.email})}"
        return render(request, "trips/invite_accept.html", context)

    existing = TripGrant.objects.filter(trip=trip, user=request.user).first()
    context["existing"] = existing
    context["raises"] = existing is not None and people.rank(existing.role) < people.rank(invite.role)
    if request.method == "POST":
        try:
            people.accept(invite, request.user, travelling=bool(request.POST.get("travelling")))
        except ValueError:  # used or cancelled in the meantime
            invite.refresh_from_db()
            context["state"] = invite.state
            return render(request, "trips/invite_accept.html", context, status=410)
        messages.success(request, f"Welcome to “{trip.name}”.")
        return redirect("trips:trip_detail", pk=trip.pk)
    return render(request, "trips/invite_accept.html", context)
