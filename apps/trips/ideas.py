"""The Ideas shelf (day-first plan, P6): things someone would like to do on the trip, with no day yet.

A ``TripIdea`` is typed on the shelf, added from a catalogue page ("Add to a trip") or made from a
bucket-list goal (bucketlists sets ``BucketListItem.trip_idea``; trips never reads bucket lists).
Everyone who can see the trip sees the shelf; anyone who may comment adds ideas and votes; editors
**put one on a day** (an item of its ``kind``, filled in from its catalogue link: ``fill``) or **add it
as an option** of a "choose one". ``idea.placed`` is what it became, and while it is set the idea is
off the shelf; deleting that item or option brings it back (``signals``).

``load(trip, viewer)`` is the shelf for the trip page: two queries (ideas with their catalogue links and
who added them; votes with their people). ``counted(trip)`` is the ideas placed on something that counts
(P4's rule: an item outside any option or in a chosen / taken one; an option chosen or taken), which is
what a finished trip's "Tick it off" offers. ``map_features(trip)`` gives the map's faint Ideas pins.
"""
from apps.approval_system.models import ApprovalStatus
from django.contrib.contenttypes.models import ContentType
from django.db.models import Prefetch
from django.urls import reverse

from .models import Lodging, Meal, Option, OptionGroup, Section, TransportLeg, TripActivity, TripIdea, Vote
from .options import counts

# What an idea can become on a day, for the "Put on a day" kind buttons.
KINDS = [("do", "Do"), ("eat", "Eat"), ("stay", "Stay"), ("travel", "Travel"), ("note", "Note")]
PLACEABLE = (TransportLeg, Lodging, TripActivity, Meal, Section, Option)


def queryset(trip):
    return (TripIdea.objects.filter(trip=trip)
            .select_related("city", "poi__city", "activity__city", "event__city", "added_by"))


def load(trip, viewer=None):
    """The trip's ideas (two queries), each with ``vote_count``, ``voters``, ``voted`` and ``on_shelf``."""
    ideas = list(queryset(trip).prefetch_related(Prefetch("votes", queryset=Vote.objects.select_related("user"))))
    for idea in ideas:
        votes = list(idea.votes.all())
        idea.vote_count = len(votes)
        idea.voters = sorted(v.user.get_full_name() or v.user.username for v in votes)
        idea.voted = bool(viewer and any(v.user_id == viewer.pk for v in votes))
        idea.on_shelf = not idea.is_placed
    return ideas


def place_of(idea):
    """The catalogue place it's at, for the map and the shelf: its place, its activity's or event's
    venue, else (as a city) its city or theirs. Returns (poi, city)."""
    poi = idea.poi or (idea.event.poi if idea.event_id and idea.event.poi_id else None) or (
        idea.activity.venue if idea.activity_id and idea.activity.venue_id else None)
    city = idea.city or (poi.city if poi else None) or (idea.event.city if idea.event_id else None) or (
        idea.activity.city if idea.activity_id else None)
    return poi, city


def city_ids(trip):
    """The cities the trip's ideas are in (for ``trip_cities``)."""
    found = []
    for idea in queryset(trip).select_related("event__poi", "activity__venue"):
        _, city = place_of(idea)
        if city is not None:
            found.append((city.pk, idea.title))
    return found


def fill(idea, item):
    """Copy the idea's notes and catalogue link onto the item just made from it (``item`` is saved)."""
    poi, city = place_of(idea)
    if isinstance(item, TripActivity):
        item.poi = poi if poi is not None and poi.approval_status == ApprovalStatus.APPROVED else None
        item.event = idea.event
        item.notes = item.notes or idea.notes
        if item.poi is None and poi is None and city is not None:
            item.place_text = city.name
    elif isinstance(item, Meal):
        item.poi = poi
        item.why_recommended = item.why_recommended or idea.notes
    elif isinstance(item, Lodging):
        item.city = item.city or city
        item.notes = item.notes or idea.notes
    elif isinstance(item, TransportLeg):
        if city is not None and not item.destination_city_id:
            item.destination_city = city
            item.destination = item.destination or city.name
            item.destination_timezone = item.destination_timezone or city.timezone or ""
        item.notes = "\n".join(p for p in (item.notes, idea.notes) if p)
    elif isinstance(item, Section):
        item.title = item.title or idea.title
        item.poi, item.activity, item.event = idea.poi, idea.activity, idea.event
        if idea.notes and not item.content.get("paragraphs"):
            item.content = {**item.content, "paragraphs": [p for p in idea.notes.split("\n\n") if p.strip()]}
    item.save()


def _placed_counts(item):
    """Whether what an idea became counts (P4 / P5's rule)."""
    if isinstance(item, Option):
        return item.chosen or (item.group.state == OptionGroup.State.SPLIT and item.travelers.exists())
    if not getattr(item, "option_id", None):
        return True
    option = item.option
    return counts(item, {option.pk: option})


def counted(trip):
    """Ideas of ``trip`` placed on something that counts, as a set of ids."""
    found = set()
    for idea in TripIdea.objects.filter(trip=trip, placed_id__isnull=False).select_related("placed_type"):
        item = idea.placed
        if item is not None and _placed_counts(item):
            found.add(idea.pk)
    return found


def return_to_shelf(sender, instance, **kwargs):
    """``post_delete`` of anything an idea can become: the idea goes back on the shelf."""
    TripIdea.objects.filter(placed_type=ContentType.objects.get_for_model(sender), placed_id=instance.pk).update(
        placed_type=None, placed_id=None)


def map_features(trip):
    """The map's Ideas layer (off by default): a faint pin per idea with a place, still on the shelf."""
    features = []
    for idea in queryset(trip).filter(placed_id__isnull=True).select_related("event__poi", "activity__venue"):
        poi, city = place_of(idea)
        spot = poi if poi is not None and poi.latitude is not None else city
        if spot is None or spot.latitude is None or spot.longitude is None:
            continue
        where = poi.name if poi is not None else city.name
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(spot.longitude), float(spot.latitude)]},
            "properties": {
                "layer": "ideas", "marker": "idea", "name": idea.title,
                "subtitle": f"Idea · {where}" if where != idea.title else "Idea on the shelf",
                "url": reverse("trips:trip_detail", args=[trip.pk]) + f"#idea-{idea.pk}",
            },
        })
    return features
