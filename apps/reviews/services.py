# reviews/services.py
"""Member reviews of activities, events, cities and places.

A review targets one published catalogue item (``TARGETS``, looked up by slug);
each member reviews an item at most once and can edit it. Visible reviews
(``is_approved``) feed the item's stored ``average_rating`` / ``review_count``,
recounted whenever a review is saved or deleted (``signals.py``).
"""
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Avg, Count
from django.http import Http404
from django.urls import reverse

from apps.activities.models import Activity
from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event
from apps.locations.models import POI, City

from .models import Review

# kind -> (model, Review field, detail URL name)
TARGETS = {
    "activity": (Activity, "activity", "activities:activity_detail"),
    "event": (Event, "event", "events:event_detail"),
    "city": (City, "location", "locations:city_detail"),
    "poi": (POI, "poi", "locations:poi_detail"),
}
REPORTS_TO_HIDE = 3  # open reports that hide a review until staff decide


def public(kind):
    """The publicly visible items of ``kind`` (what may be reviewed)."""
    model = TARGETS[kind][0]
    if model is Activity:
        return Activity.get_public_activities()
    return model.objects.filter(approval_status=ApprovalStatus.APPROVED)


def get_target(kind, slug):
    """The published item, or 404."""
    if kind not in TARGETS:
        raise Http404
    target = public(kind).filter(slug=slug).first()
    if target is None:
        raise Http404
    return target


def kind_of(target):
    for kind, (model, _, _) in TARGETS.items():
        if isinstance(target, model):
            return kind
    return None


def target_url(target):
    return reverse(TARGETS[kind_of(target)][2], args=[target.slug])


def reviews_of(target):
    """Visible reviews of ``target``, newest first."""
    field = TARGETS[kind_of(target)][1]
    return Review.objects.filter(**{field: target}, is_approved=True).select_related("user")


def review_by(user, target):
    if not user.is_authenticated:
        return None
    field = TARGETS[kind_of(target)][1]
    return Review.objects.filter(**{field: target}, user=user).first()


def new_review(user, target):
    """An unsaved review of ``target`` by ``user``."""
    kind = kind_of(target)
    return Review(user=user, review_type="location" if kind == "city" else kind, **{TARGETS[kind][1]: target})


def upsert_review(user, target, rating, comment, title="", visit_date=None, verified=False):
    """Create or update ``user``'s review of ``target``; returns it."""
    review = review_by(user, target) or new_review(user, target)
    review.rating, review.comment, review.title = rating, comment, title
    if visit_date is not None:
        review.visit_date = visit_date
    if verified:
        review.is_verified_visit = True
    review.save()
    return review


def recount(target):
    """Store ``average_rating`` / ``review_count`` on ``target`` from its visible reviews."""
    stats = reviews_of(target).aggregate(avg=Avg("rating"), n=Count("pk"))
    average = (Decimal(stats["avg"]).quantize(Decimal("0.01"), ROUND_HALF_UP) if stats["avg"] is not None else None)
    if target.average_rating != average or target.review_count != stats["n"]:
        type(target).objects.filter(pk=target.pk).update(average_rating=average, review_count=stats["n"])
        target.average_rating, target.review_count = average, stats["n"]
