# pages/staff.py
"""Staff dashboard: site stats and the things that need a staff member's attention.

Lives in `pages` (layer 5) because it reads from every app. Each "attention"
entry is a dict(title, count, detail, url, items, tone), built only from
read-only queries; nothing here changes data.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.views import redirect_to_login
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Exists, OuterRef, Q
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import RoleRequest
from apps.activities.models import Activity
from apps.approval_system.models import ApprovalLog, ApprovalSettings, ApprovalStatus
from apps.bucketlists.models import BucketListItem
from apps.core.utils.breadcrumbs import build_breadcrumbs
from apps.events.models import Event
from apps.locations.models import POI, City, Country, Region
from apps.media_app.models import Media
from apps.trips.models import Trip

LIST_LIMIT = 5

# Content that goes through approval, in the order it is shown.
APPROVABLE = [
    ("Activities", Activity), ("Events", Event), ("Places (POIs)", POI),
    ("Cities", City), ("Regions", Region), ("Countries", Country),
]


def _review_url(obj):
    ct = ContentType.objects.get_for_model(obj)
    return reverse("approval_system:review_item", args=[ct.pk, obj.pk])


def _admin_url(obj):
    meta = obj._meta
    return reverse(f"admin:{meta.app_label}_{meta.model_name}_change", args=[obj.pk])


def _age(dt, now):
    if not dt:
        return ""
    hours = int((now - dt).total_seconds() // 3600)
    return f"{hours} h" if hours < 48 else f"{hours // 24} days"


def _pending_approvals(now, sla_hours):
    """One row per approvable model with its pending count, oldest age and overdue count."""
    cutoff = now - timedelta(hours=sla_hours)
    rows, items = [], []
    for label, model in APPROVABLE:
        pending = model.objects.filter(approval_status=ApprovalStatus.PENDING)
        stats = pending.aggregate(n=Count("pk"), overdue=Count("pk", filter=Q(submitted_at__lt=cutoff)))
        if not stats["n"]:
            continue
        oldest = pending.order_by("submitted_at", "pk").first()
        rows.append({"label": label, "count": stats["n"], "overdue": stats["overdue"],
                     "oldest": _age(oldest.submitted_at, now)})
        for obj in pending.order_by("submitted_at", "pk")[:LIST_LIMIT]:
            items.append({"text": str(obj), "meta": f"{label} · waiting {_age(obj.submitted_at, now) or '?'}",
                          "url": _review_url(obj), "submitted": obj.submitted_at or now})
    items.sort(key=lambda i: i["submitted"])
    return rows, items[:LIST_LIMIT]


def _attention(now, sla_hours):
    """Everything waiting on staff, most urgent first; entries with nothing to do are dropped."""
    entries = []

    rows, items = _pending_approvals(now, sla_hours)
    total = sum(r["count"] for r in rows)
    overdue = sum(r["overdue"] for r in rows)
    entries.append({
        "key": "approvals", "title": "Submissions waiting for review", "count": total,
        "detail": (f"{overdue} past the {sla_hours} h review target. " if overdue else "")
                  + ", ".join(f"{r['label']} {r['count']}" for r in rows),
        "url": reverse("approval_system:dashboard"), "items": items,
        "tone": "danger" if overdue else "warning",
    })

    role_requests = RoleRequest.objects.filter(status=RoleRequest.Status.PENDING).select_related("user").order_by("created_at")
    entries.append({
        "key": "roles", "title": "Role requests", "count": role_requests.count(),
        "detail": "People asking to become a vendor or content provider.",
        "url": reverse("staff:admin_role_requests"),
        "items": [{"text": f"@{r.user.username}: {r.get_requested_role_display()}",
                   "meta": f"waiting {_age(r.created_at, now)}",
                   "url": reverse("staff:admin_role_request_detail", args=[r.pk])} for r in role_requests[:LIST_LIMIT]],
        "tone": "warning",
    })

    unlinked = Event.objects.filter(city__isnull=True).exclude(approval_status=ApprovalStatus.REJECTED).select_related("country")
    entries.append({
        "key": "event_cities", "title": "Events with a city that isn't in the catalogue", "count": unlinked.count(),
        "detail": "Link each to a city (or create it) from the event page.",
        "url": None,
        "items": [{"text": e.name, "meta": e.place_name, "url": reverse("events:event_detail", args=[e.slug])}
                  for e in unlinked.order_by("start_date")[:LIST_LIMIT]],
        "tone": "info",
    })

    has_regions = Region.objects.filter(country=OuterRef("country"))
    no_region = (City.objects.filter(region__isnull=True).filter(Exists(has_regions))
                 .exclude(approval_status=ApprovalStatus.REJECTED).select_related("country"))
    entries.append({
        "key": "city_regions", "title": "Cities without a region", "count": no_region.count(),
        "detail": "Their country has regions; set one in the admin.",
        "url": reverse("admin:locations_city_changelist") + "?region__isnull=True",
        "items": [{"text": c.name, "meta": c.country.name, "url": _admin_url(c)} for c in no_region.order_by("name")[:LIST_LIMIT]],
        "tone": "info",
    })

    today = now.date()
    upcoming = Event.objects.filter(related_activity=OuterRef("pk"), start_date__gte=today)
    yearly = (Activity.objects.filter(recurrence="yearly", approval_status=ApprovalStatus.APPROVED)
              .exclude(Exists(upcoming)))
    entries.append({
        "key": "yearly", "title": "Yearly activities with no upcoming dates", "count": yearly.count(),
        "detail": "Add the next occurrence as an event (“Add <year> dates” on the last one).",
        "url": None,
        "items": [{"text": a.name, "meta": a.place_name or "", "url": reverse("activities:activity_detail", args=[a.slug])}
                  for a in yearly.order_by("name")[:LIST_LIMIT]],
        "tone": "info",
    })

    loose = Activity.objects.filter(city__isnull=True, country__isnull=True).exclude(suggested_location="")
    entries.append({
        "key": "activity_places", "title": "Activities whose place isn't linked", "count": loose.count(),
        "detail": "They have a typed location but no country / city.",
        "url": None,
        "items": [{"text": a.name, "meta": a.suggested_location, "url": reverse("activities:activity_edit", args=[a.slug])}
                  for a in loose.order_by("name")[:LIST_LIMIT]],
        "tone": "info",
    })

    heic = Media.objects.filter(Q(file__iendswith=".heic") | Q(file__iendswith=".heif"))
    entries.append({
        "key": "heic", "title": "HEIC images most browsers can't show", "count": heic.count(),
        "detail": "Uploaded before HEIC uploads were converted to JPEG; re-upload them.",
        "url": None,
        "items": [{"text": m.title or m.file.name.rsplit("/", 1)[-1], "meta": f"by @{m.uploaded_by.username}",
                   "url": _admin_url(m)} for m in heic.select_related("uploaded_by")[:LIST_LIMIT]],
        "tone": "info",
    })

    User = get_user_model()
    placeholder = User.objects.filter(email__iendswith="@noemail.invalid")
    entries.append({
        "key": "emails", "title": "Accounts with a placeholder email", "count": placeholder.count(),
        "detail": "They can't receive password resets until a real address is set.",
        "url": reverse("admin:accounts_user_changelist") + "?q=noemail.invalid",
        "items": [{"text": u.username, "meta": u.email, "url": _admin_url(u)} for u in placeholder.order_by("username")[:LIST_LIMIT]],
        "tone": "info",
    })

    draft_legal = [k for k, v in settings.LEGAL.items() if str(v).startswith("[")]
    entries.append({
        "key": "legal", "title": "Legal pages still have placeholders", "count": len(draft_legal),
        "detail": "Set " + ", ".join(f"LEGAL_{k.upper()}" for k in draft_legal) + " in .env." if draft_legal else "",
        "url": reverse("pages:terms"), "items": [], "tone": "info",
    })

    return [e for e in entries if e["count"]]


def _stats(now):
    User = get_user_model()
    week, month = now - timedelta(days=7), now - timedelta(days=30)
    users = User.objects.aggregate(
        total=Count("pk", filter=Q(is_active=True)),
        new_week=Count("pk", filter=Q(date_joined__gte=week)),
        new_month=Count("pk", filter=Q(date_joined__gte=month)),
        active_week=Count("pk", filter=Q(last_login__gte=week)),
    )
    items = BucketListItem.objects.aggregate(
        total=Count("pk", filter=~Q(status="abandoned")),
        completed=Count("pk", filter=Q(status="completed")),
        with_trip=Count("pk", filter=Q(trip__isnull=False, trip__deleted_at__isnull=True)),
        new_week=Count("pk", filter=Q(created_at__gte=week)),
    )
    approved = Q(approval_status=ApprovalStatus.APPROVED)
    return {
        "users": users,
        "bucket": items,
        "trips": Trip.objects.live().aggregate(total=Count("pk"), upcoming=Count("pk", filter=Q(start_date__gte=now.date())),
                                               new_week=Count("pk", filter=Q(created_at__gte=week))),
        "catalogue": [
            ("Activities", Activity.objects.filter(approved).count(), reverse("activities:activity_list")),
            ("Upcoming events", Event.objects.filter(approved, start_date__gte=now.date()).count(), reverse("events:event_list")),
            ("Countries", Country.objects.filter(approved).count(), reverse("locations:country_list")),
            ("Cities", City.objects.filter(approved).count(), reverse("locations:city_list")),
            ("Places (POIs)", POI.objects.filter(approved).count(), reverse("locations:poi_list")),
            ("Media files", Media.objects.count(), reverse("admin:media_app_media_changelist")),
        ],
    }


def staff_dashboard(request):
    """Site overview for staff (``User.can_access_staff``); 403 for other signed-in users."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if not request.user.can_access_staff:
        raise PermissionDenied
    now = timezone.now()
    sla_hours = ApprovalSettings.get_settings().review_sla_hours
    User = get_user_model()
    return render(request, "pages/staff_dashboard.html", {
        "attention": _attention(now, sla_hours),
        "stats": _stats(now),
        "new_users": User.objects.order_by("-date_joined")[:LIST_LIMIT],
        "recent_reviews": ApprovalLog.objects.select_related("performed_by", "content_type")[:8],
        "recent_admin": LogEntry.objects.select_related("user", "content_type")[:8],
        "breadcrumb_list": build_breadcrumbs([("Staff", None)]),
    })
