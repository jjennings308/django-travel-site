# recommendations/services.py
"""Rule-based suggestions for the dashboard ("Recommended for you").

``recommendations`` sits beside ``bucketlists`` in layer 4 and may not import
it, so the caller (``pages``, layer 5) passes in what the user's bucket list
already covers. Candidates are public activities and upcoming events, scored:

  - an upcoming date of an activity whose goal has no date yet  -> "New date for your goal"
  - same category as the user's goals                           -> "Matches your interests"
  - in a country the user's goals are in                        -> "Near your plans"
  - otherwise the most bucket-listed                            -> "Popular"

Ties go to featured items, then newest. The recommendation models in this app
are unused; they were scaffolding for something larger.
"""
from dataclasses import dataclass, field

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.activities.models import Activity
from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event

POOL = 60  # candidates looked at per kind


@dataclass
class Goals:
    """What the user's bucket list already covers (ids)."""
    activity_ids: set = field(default_factory=set)
    event_ids: set = field(default_factory=set)
    undated_activity_ids: set = field(default_factory=set)  # activity goals with no date yet
    category_ids: set = field(default_factory=set)
    country_ids: set = field(default_factory=set)


def _card(obj, kind, tag, description):
    url = reverse("activities:activity_detail" if kind == "activity" else "events:event_detail", args=[obj.slug])
    return {
        "tag": tag, "title": obj.name, "description": description, "url": url, "kind": kind, "obj": obj,
        "image_url": obj.featured_media.file.url if obj.featured_media_id else None,
    }


def for_user(goals, limit=3):
    """Up to ``limit`` suggestion dicts (tag, title, description, image_url, url, kind, obj)."""
    today = timezone.localdate()
    scored = []

    events = (Event.objects.filter(approval_status=ApprovalStatus.APPROVED, start_date__gte=today)
              .exclude(pk__in=goals.event_ids)
              .select_related("category", "city__country", "country", "related_activity", "featured_media")
              .order_by("start_date")[:POOL])
    for event in events:
        country_id = event.city.country_id if event.city_id else event.country_id
        when = f"{event.start_date:%b} {event.start_date.day}, {event.start_date.year}"
        if event.related_activity_id in goals.undated_activity_ids:
            score, tag = 100, "New date for your goal"
            text = f"{event.related_activity.name} is on your list: this date is {when}, {event.place_name}."
        elif event.category_id in goals.category_ids:
            score, tag, text = 30, "Matches your interests", f"{when} · {event.place_name}. {event.short_description}"
        elif country_id in goals.country_ids:
            score, tag, text = 20, "Near your plans", f"{when} · {event.place_name}. {event.short_description}"
        else:
            score, tag, text = 0, "Popular", f"{when} · {event.place_name}. {event.short_description}"
        if event.related_activity_id in goals.activity_ids and score < 100:
            continue  # its activity is already a (dated) goal
        scored.append((score, event.bucket_list_count, event.is_featured, event.created_at, _card(event, "event", tag, text)))

    activities = (Activity.get_public_activities()
                  .exclude(pk__in=goals.activity_ids)
                  .select_related("category", "city", "region", "country", "featured_media")
                  .order_by("-bucket_list_count", "-created_at")[:POOL])
    for activity in activities:
        text = activity.short_description or activity.description
        if activity.category_id in goals.category_ids:
            score, tag = 30, "Matches your interests"
        elif activity.country_id in goals.country_ids:
            score, tag = 20, "Near your plans"
        else:
            score, tag = 0, "Popular"
        scored.append((score, activity.bucket_list_count, activity.is_featured, activity.created_at,
                       _card(activity, "activity", tag, text)))

    scored.sort(key=lambda s: s[:4], reverse=True)
    # One card per activity: its dated event (when one is suggested) or the activity itself.
    picked, activities_seen = [], set()
    for *_, card in scored:
        activity_id = card["obj"].pk if card["kind"] == "activity" else card["obj"].related_activity_id
        if activity_id and activity_id in activities_seen:
            continue
        if activity_id:
            activities_seen.add(activity_id)
        picked.append(card)
        if len(picked) == limit:
            break
    return picked
