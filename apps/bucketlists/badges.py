# bucketlists/badges.py
"""Badges: milestones earned from what a user does with their bucket list.

Each badge is a rule that counts something (goals added, ticked off, countries,
events, trips, photos) and a target. ``award_badges(user)`` records newly earned
ones as BucketListMilestone rows (code = the badge's code) and, unless told not
to, sends a notification. It is cheap enough to run after every goal change.
"""
from dataclasses import dataclass

from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone

from .models import BucketListItem, BucketListMilestone


@dataclass(frozen=True)
class Badge:
    code: str
    title: str
    description: str
    icon: str            # Bootstrap icon class
    counter: str         # key into _counts()
    target: int
    milestone_type: str  # BucketListMilestone.MILESTONE_TYPES


BADGES = [
    Badge("first_goal", "Dreamer", "Added your first goal.", "bi-stars", "added", 1, "items_added"),
    Badge("ten_goals", "Big dreamer", "Ten goals on your list.", "bi-list-stars", "added", 10, "items_added"),
    Badge("first_done", "First adventure", "Ticked off your first goal.", "bi-trophy", "done", 1, "items_completed"),
    Badge("five_done", "Adventurer", "Five goals ticked off.", "bi-award", "done", 5, "items_completed"),
    Badge("ten_done", "Seasoned traveller", "Ten goals ticked off.", "bi-award-fill", "done", 10, "items_completed"),
    Badge("twentyfive_done", "Legend", "Twenty-five goals ticked off.", "bi-gem", "done", 25, "items_completed"),
    Badge("three_countries", "Globetrotter", "Goals done in three countries.", "bi-globe-americas", "countries", 3, "countries_visited"),
    Badge("ten_countries", "World explorer", "Goals done in ten countries.", "bi-globe2", "countries", 10, "countries_visited"),
    Badge("first_event", "Front row", "Went to an event on your list.", "bi-ticket-perforated", "events", 1, "events_attended"),
    Badge("first_trip", "Trip planner", "Planned a trip for a goal.", "bi-airplane", "trips", 1, "custom"),
    Badge("first_photo", "Snapshot", "Added a photo to an adventure.", "bi-camera", "photos", 1, "custom"),
]


def _counts(user):
    """The numbers the badges are measured against (a handful of queries)."""
    from apps.media_app.models import Media
    items = BucketListItem.objects.filter(user=user)
    done = items.filter(status="completed")
    countries = set()
    for row in done.values("city__country_id", "activity__country_id", "event__city__country_id",
                           "event__country_id", "pois__city__country_id"):
        countries.update(v for v in row.values() if v)
    photos = Media.objects.filter(content_type=ContentType.objects.get_for_model(BucketListItem),
                                  object_id__in=items.values("pk"), media_type="image")
    return {
        "added": items.count(),
        "done": done.count(),
        "countries": len(countries),
        "events": done.filter(event__isnull=False).count(),
        "trips": items.filter(trip__isnull=False).count(),
        "photos": photos.count(),
    }


def progress(user):
    """[(badge, earned_at or None, current, target)] for every badge, earned first."""
    counts = _counts(user)
    earned = {m.code: m.achieved_date for m in BucketListMilestone.objects.filter(user=user, is_achieved=True).exclude(code="")}
    rows = [(b, earned.get(b.code), min(counts[b.counter], b.target), b.target) for b in BADGES]
    rows.sort(key=lambda r: (r[1] is None, -(r[1].timestamp()) if r[1] else 0, -r[2] / r[3]))
    return rows


def award_badges(user, notify=True):
    """Record every badge ``user`` has newly earned; returns them. Idempotent."""
    if user is None or not user.is_authenticated:
        return []
    counts = _counts(user)
    have = set(BucketListMilestone.objects.filter(user=user).exclude(code="").values_list("code", flat=True))
    new = []
    for badge in BADGES:
        if badge.code in have or counts[badge.counter] < badge.target:
            continue
        BucketListMilestone.objects.create(
            user=user, code=badge.code, milestone_type=badge.milestone_type, title=badge.title,
            description=badge.description, target_count=badge.target, current_count=counts[badge.counter],
            is_achieved=True, achieved_date=timezone.now(), badge_icon=badge.icon)
        new.append(badge)
        if notify:
            from apps.notifications.services import notify as send
            send(user, "badge_earned", f"You earned a badge: {badge.title}", f"{badge.title}: {badge.description}",
                 reverse("bucketlists:adventures"))
    return new
