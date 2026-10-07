"""Staff dashboard aggregates.

A staff-only read of the whole site, so it deliberately does *not* go through
``Trip.objects.visible_to``: staff see every live trip anyway, and a dashboard
that respected grants would show a different picture to each staff member for
no reason — these are facts about the site, not about the reader. Soft-deleted
trips are counted separately rather than mixed into the live totals.

Aggregation only, no request, so the view contributes nothing but the
permission check and this stays testable without one. Counts use
``.aggregate()`` and one grouped query per breakdown rather than per-row
``__str__`` loops: a staff page should not issue a query per trip to draw a
bar chart.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import Role, UserRole

from .models import (
    BookingTask,
    Comment,
    Confirmation,
    Contact,
    Day,
    Lodging,
    Meal,
    Section,
    TransportLeg,
    Traveler,
    Trip,
    TripGrant,
    TripRole,
)

User = get_user_model()


def _grouped(queryset, field):
    """``{value: count}`` for one grouped count, in one query."""
    return {
        row[field]: row["n"]
        for row in queryset.values(field).annotate(n=Count("id"))
    }


def _breakdown(choices, counts):
    """Ordered ``choices`` rows with a count and two percentages each.

    ``pct`` is against the largest count in the group, not the total, so the
    biggest bar always fills the track and the rest read as proportions of it.
    ``share`` is against the total, for the one segmented bar (trip status)
    where the segments have to add up to the whole track.
    The percentages are computed here rather than in the template because the
    template has no arithmetic and the max would have to be found there anyway.
    """
    rows = [
        {"value": value, "label": label, "count": counts.get(value, 0)}
        for value, label in choices
    ]
    largest = max((row["count"] for row in rows), default=0)
    total = sum(row["count"] for row in rows)
    for row in rows:
        row["pct"] = round(row["count"] * 100 / largest) if largest else 0
        row["share"] = round(row["count"] * 100 / total, 1) if total else 0
    return rows


def build_dashboard():
    """Every figure the dashboard shows, as a plain nested dict."""
    today = timezone.localdate()
    week_ago = timezone.now() - timedelta(days=7)

    live = Trip.objects.live()

    # -- people -----------------------------------------------------------
    accounts = User.objects.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(is_active=True)),
        inactive=Count("id", filter=Q(is_active=False)),
        staff=Count("id", filter=Q(is_staff=True)),
        superusers=Count("id", filter=Q(is_superuser=True)),
        never_logged_in=Count("id", filter=Q(last_login__isnull=True)),
    )
    travelers = Traveler.objects.aggregate(
        total=Count("id"),
        linked=Count("id", filter=Q(user__isnull=False)),
        unlinked=Count("id", filter=Q(user__isnull=True)),
    )
    # Trip access by role: one count per grant on a live trip. A person with
    # grants on three trips is counted three times, once per trip.
    roles = _breakdown(
        TripRole.choices, _grouped(TripGrant.objects.filter(trip__in=live), "role")
    )
    creators = UserRole.objects.filter(role=Role.CREATOR).count()
    # Staff need no grants, so this is "accounts that can reach no trip unless
    # they are staff" rather than "unconfigured".
    users_without_role = User.objects.filter(trip_grants__isnull=True).count()

    # -- trips ------------------------------------------------------------
    trips = {
        "total": live.count(),
        "deleted": Trip.objects.deleted().count(),
        "ready": live.filter(status=Trip.Status.READY_TO_GO).count(),
        "upcoming": live.filter(end_date__gte=today).count(),
        "past": live.filter(end_date__lt=today).count(),
        "unowned": live.filter(created_by__isnull=True).count(),
        "public": live.filter(public_token__isnull=False).count(),
        "without_grants": live.filter(grants__isnull=True).count(),
        "by_status": _breakdown(Trip.Status.choices, _grouped(live, "status")),
    }

    # -- planning work ----------------------------------------------------
    # The completed alias is `completed`, not `done`: an aggregate alias is
    # visible to the other expressions in the same aggregate() call, so
    # `done=Count(...)` would shadow the `done` field and make every
    # `Q(done=False)` below resolve against the aggregate.
    tasks = {
        **BookingTask.objects.aggregate(
            total=Count("id"),
            completed=Count("id", filter=Q(done=True)),
            outstanding=Count("id", filter=Q(done=False)),
            overdue=Count("id", filter=Q(done=False, due__lt=today)),
        ),
        "trips_with_outstanding": live.filter(booking_tasks__done=False)
        .distinct()
        .count(),
        "by_priority": _breakdown(
            BookingTask.Priority.choices,
            _grouped(BookingTask.objects.filter(done=False), "priority"),
        ),
    }

    tasks["done_pct"] = (
        round(tasks["completed"] * 100 / tasks["total"]) if tasks["total"] else 0
    )

    # -- content ----------------------------------------------------------
    content = {
        "days": Day.objects.count(),
        "sections": Section.objects.count(),
        "meals": Meal.objects.count(),
        "lodging": Lodging.objects.count(),
        "transport": TransportLeg.objects.count(),
        "confirmations": Confirmation.objects.count(),
        "contacts": Contact.objects.count(),
        "comments": Comment.objects.count(),
        "comments_recent": Comment.objects.filter(created_at__gte=week_ago).count(),
    }
    sections_by_type = _breakdown(
        Section.Type.choices, _grouped(Section.objects, "section_type")
    )

    # -- access -----------------------------------------------------------
    access = {
        "grants": TripGrant.objects.count(),
        "users_with_grants": TripGrant.objects.values("user").distinct().count(),
    }

    # Annotated, not left to ``Trip.outstanding_booking_tasks``: the property
    # is fine for one trip but would fire a COUNT per row here.
    recent_trips = list(
        live.annotate(
            outstanding_task_count=Count(
                "booking_tasks",
                filter=Q(booking_tasks__done=False),
                distinct=True,
            )
        ).order_by("-updated_at")[:6]
    )

    return {
        "accounts": accounts,
        "travelers": travelers,
        "roles": roles,
        "users_without_role": users_without_role,
        "creators": creators,
        "trips": trips,
        "tasks": tasks,
        "content": content,
        "sections_by_type": sections_by_type,
        "access": access,
        "recent_trips": recent_trips,
        "generated_at": timezone.now(),
    }
