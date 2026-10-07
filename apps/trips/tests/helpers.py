"""Shared access set-up for the trips tests.

Roles are per trip: ``TripRole`` values go on the ``TripGrant``. ``Role.CREATOR``
is the one app-wide capability left on ``accounts.UserRole`` ("may create
trips"); passed with a trip it also gives an editor grant, which is what the
role migration (trips 0014) did with existing creators.
"""

from apps.accounts.models import Role, UserRole
from apps.trips.models import TRIP_ROLE_RANK, TripGrant, TripRole


def give(user, *roles, trip=None, granted_by=None):
    """Grant ``roles`` to ``user``; trip roles need ``trip``."""
    creator = Role.CREATOR in roles
    trip_roles = [role for role in roles if role != Role.CREATOR]
    if creator:
        UserRole.objects.create(user=user, role=Role.CREATOR, granted_by=granted_by)
    if trip is not None:
        if trip_roles:
            role = max(trip_roles, key=TRIP_ROLE_RANK.get)
        elif creator:
            role = TripRole.EDITOR
        else:
            raise ValueError("a TripGrant needs a role")
        TripGrant.objects.create(trip=trip, user=user, role=role, granted_by=granted_by)
    return user
