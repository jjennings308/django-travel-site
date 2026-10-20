"""A member's recent activity on their profile page (the profile's "Recent Activity" box).

Lives in ``pages`` because it reads goals, badges, reviews, the catalogue and trips; the profile page
(``accounts``, which may import none of them) loads it after the page through the shell partial
``partials/_profile_activity.html``. Others see only public things — public goals, badges, approved
reviews, published catalogue items the member added. The member also sees their private goals and the
trips they finished (marked "Only you"). One small query per kind, newest first.
"""
from dataclasses import dataclass
from datetime import datetime, time

from django.urls import reverse
from django.utils import timezone

from apps.activities.models import Activity
from apps.approval_system.models import ApprovalStatus
from apps.bucketlists.badges import BADGES
from apps.bucketlists.models import BucketListItem, BucketListMilestone
from apps.events.models import Event
from apps.locations.models import POI
from apps.reviews.models import Review
from apps.reviews.services import target_url as review_target_url
from apps.trips.models import Trip

SHOWN = 10


@dataclass
class Entry:
    when: datetime
    icon: str
    verb: str
    title: str
    url: str = ""
    private: bool = False
    plural: str = ""  # "Added 6 places:" — same-day runs of one kind fold into one line with this verb
    more: list = None  # the other titles of a folded line


def _fold(entries):
    """Three or more of one kind on one day (wherever they fall in the list) become one line, at the
    newest one's place: "Added 6 places: A, B, C +3". ``entries`` is newest first."""
    groups = {}
    for e in entries:
        if e.plural:
            groups.setdefault((e.plural, e.private, timezone.localdate(e.when)), []).append(e)
    out = []
    for e in entries:
        run = groups.get((e.plural, e.private, timezone.localdate(e.when))) if e.plural else None
        if not run or len(run) < 3:
            out.append(e)
        elif run[0] is e:
            e.verb = e.plural.format(n=len(run))
            e.more = [r.title for r in run[1:]]
            out.append(e)
    return out


def _at(day):
    """A date as a datetime (noon, current zone) so it sorts among timestamps."""
    return timezone.make_aware(datetime.combine(day, time(12)))


def feed(owner, viewer, limit=SHOWN):
    own = viewer.is_authenticated and viewer.pk == owner.pk
    entries = []
    goals = (BucketListItem.objects.filter(user=owner).select_related("activity", "city", "event")
             .prefetch_related("pois"))
    if not own:
        goals = goals.filter(is_public=True)
    for item in goals.filter(status="completed", completed_date__isnull=False).order_by("-completed_date")[:limit]:
        entries.append(Entry(_at(item.completed_date), "bi-check2-circle", "Ticked off", item.title,
                             item.target_url or "", private=not item.is_public, plural="Ticked off {n} goals:"))
    for item in goals.order_by("-created_at")[:limit]:
        entries.append(Entry(item.created_at, "bi-plus-circle", "Added to bucket list", item.title,
                             item.target_url or "", private=not item.is_public, plural="Added {n} goals to bucket list:"))
    titles = {badge.code: badge for badge in BADGES}
    for milestone in BucketListMilestone.objects.filter(user=owner).exclude(code="").order_by("-created_at")[:limit]:
        badge = titles.get(milestone.code)
        entries.append(Entry(milestone.created_at, badge.icon if badge else "bi-award", "Earned the badge",
                             badge.title if badge else milestone.title))
    for review in (Review.objects.filter(user=owner, is_approved=True)
                   .select_related("activity", "event", "location", "poi").order_by("-created_at")[:limit]):
        target = review.target
        if target is not None:
            entries.append(Entry(review.created_at, "bi-star", f"Reviewed ({review.rating}★)", target.name,
                                 review_target_url(target)))  # never folded: each has its own rating
    approved = {"approval_status": ApprovalStatus.APPROVED}
    for activity in Activity.get_public_activities().filter(created_by=owner).order_by("-created_at")[:limit]:
        entries.append(Entry(activity.created_at, "bi-signpost-2", "Added the activity", activity.name,
                             reverse("activities:activity_detail", args=[activity.slug]), plural="Added {n} activities:"))
    for event in Event.objects.filter(created_by=owner, **approved).order_by("-created_at")[:limit]:
        entries.append(Entry(event.created_at, "bi-calendar-event", "Added the event", event.name,
                             reverse("events:event_detail", args=[event.slug]), plural="Added {n} events:"))
    for place in POI.objects.filter(submitted_by=owner, **approved).order_by("-created_at")[:limit]:
        entries.append(Entry(place.created_at, "bi-geo-alt", "Added the place", place.name,
                             reverse("locations:poi_detail", args=[place.slug]), plural="Added {n} places:"))
    if own:
        finished = (Trip.objects.live().filter(travelers__user=owner, end_date__lt=timezone.localdate())
                    .distinct().order_by("-end_date")[:limit])
        for trip in finished:
            entries.append(Entry(_at(trip.end_date), "bi-airplane", "Finished the trip", trip.name,
                                 reverse("trips:trip_detail", args=[trip.pk]), private=True))
    entries.sort(key=lambda e: e.when, reverse=True)
    return _fold(entries)[:limit]
