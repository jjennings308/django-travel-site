"""The Ideas shelf's pages (day-first plan, P6). The rules live in ``ideas.py``.

Anyone who may comment on a trip adds ideas (``idea_add``), edits or removes their own (editors any)
and votes (``idea_vote``); editors put one on a day (``idea_place``: an item of its kind, filled in from
its catalogue link, opened like + Add's) or add it as an option of a "choose one" (``idea_option``).
``idea_from_catalogue`` is "Add to a trip" on a catalogue place, activity, event or city page: it lists
the member's trips they may comment on and adds the item to the chosen one's shelf.
"""
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Max
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.activities.models import Activity
from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event
from apps.locations.models import POI, City

from . import ideas, quick_add as parser, trip_cities
from .forms import IdeaForm
from .models import Day, Option, OptionGroup, Trip, TripIdea, Vote
from .views import _back, _is_panel, _make_on_day, _readable_trip


def _shelf(trip, idea=None):
    return reverse("trips:trip_detail", args=[trip.pk]) + (f"#idea-{idea.pk}" if idea else "#ideas")


def _idea_of(request, pk, idea_pk, action):
    trip = _readable_trip(request, pk, action)
    return trip, get_object_or_404(TripIdea.objects.filter(trip=trip), pk=idea_pk)


def _may_change(request, trip, idea):
    """Whoever added an idea may change it while they may comment; editors any."""
    return trip.can(request.user, "edit") or (idea.added_by_id == request.user.pk and trip.can(request.user, "comment"))


@login_required
@require_POST
def idea_add(request, pk):
    """Type an idea onto the shelf (anyone who may comment)."""
    trip = _readable_trip(request, pk, "comment")
    form = IdeaForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Type the idea first.")
        return redirect(_shelf(trip))
    idea = form.save(commit=False)
    idea.trip, idea.added_by = trip, request.user
    idea.save()
    messages.success(request, f"Added “{idea.title}” to the ideas.")
    return redirect(_shelf(trip, idea))


@login_required
def idea_edit(request, pk, idea_pk):
    trip, idea = _idea_of(request, pk, idea_pk, "comment")
    if not _may_change(request, trip, idea):
        raise PermissionDenied
    form = IdeaForm(request.POST or None, instance=idea)
    back = _back(request, _shelf(trip, idea))
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Saved “{idea.title}”.")
        return redirect(back)
    return render(request, "trips/idea_form.html", {"trip": trip, "idea": idea, "form": form, "next": back})


@login_required
@require_POST
def idea_delete(request, pk, idea_pk):
    trip, idea = _idea_of(request, pk, idea_pk, "comment")
    if not _may_change(request, trip, idea):
        raise PermissionDenied
    title = idea.title
    idea.delete()
    messages.success(request, f"Removed the idea “{title}”.")
    return redirect(_shelf(trip))


@login_required
@require_POST
def idea_vote(request, pk, idea_pk):
    """👍 an idea, or take it back (anyone who may comment). 204 for a background ``fetch``."""
    trip, idea = _idea_of(request, pk, idea_pk, "comment")
    vote, made = Vote.objects.get_or_create(user=request.user, idea=idea)
    if not made:
        vote.delete()
    if request.headers.get("X-Requested-With") == "fetch":
        return HttpResponse(status=204)
    return redirect(_back(request, _shelf(trip, idea)))


@login_required
@require_POST
def idea_place(request, pk, idea_pk):
    """Put an idea on a day (editors): the item of its kind (or the kind clicked), filled in from the
    idea, opened on its page — as JSON for the trip page's panel, like + Add."""
    trip, idea = _idea_of(request, pk, idea_pk, "edit")
    day = get_object_or_404(Day.objects.filter(trip=trip), pk=request.POST.get("day") or 0)
    kind = request.POST.get("kind") if request.POST.get("kind") in parser.KINDS else idea.kind
    item, url, anchor, label = _make_on_day(trip, day, parser.parse(idea.title, kind=kind))
    ideas.fill(idea, item)
    idea.place_on(item)
    trip_cities.sync(trip)
    messages.success(request, f"Put “{idea.title}” on Day {day.day_number}.")
    back = reverse("trips:trip_detail", args=[trip.pk]) + f"#day-{day.day_number}"
    if request.headers.get("X-Requested-With") == "fetch" and not _is_panel(request):
        return JsonResponse({"url": url, "anchor": anchor})
    return redirect(f"{url}?next={quote(back)}")


@login_required
@require_POST
def idea_option(request, pk, idea_pk):
    """Add an idea as an option (editors): of an undecided "choose one" (``group``) whose kind fits the idea's
    (``ideas.fits``; "Anything" takes any idea), or of a new one on a day (``day``, with ``prompt``), which
    gets the idea's kind (typed-choices T3). On a typed choice the idea's notes and catalogue link go into
    the option's own fields (``ideas.fill_option``; Pick makes the item); on an "Anything" choice an idea
    linked to the catalogue gets its item inside the option, so the link and its notes come along. Opens
    the group's page."""
    trip, idea = _idea_of(request, pk, idea_pk, "edit")
    # The shelf's one select sends "group-<id>" (an undecided choice) or "day-<id>" (a new one there).
    where, _, number = request.POST.get("target", "").partition("-")
    group_pk = request.POST.get("group") or (number if where == "group" else "")
    day_pk = request.POST.get("day") or (number if where == "day" else "")
    if group_pk:
        group = get_object_or_404(OptionGroup.objects.filter(trip=trip, state=OptionGroup.State.OPEN),
                                  pk=group_pk if str(group_pk).isdigit() else 0)
        if not ideas.fits(idea, group):
            messages.error(request, f"“{group.prompt}” is a choice about {group.get_kind_display().lower()}: "
                                    f"“{idea.title}” doesn't fit it.")
            return redirect(_shelf(trip, idea))
    else:
        day = get_object_or_404(Day.objects.filter(trip=trip), pk=day_pk if str(day_pk).isdigit() else 0)
        prompt = " ".join(request.POST.get("prompt", "").split())[:200] or f"{idea.title} or …"
        group = OptionGroup.objects.create(trip=trip, day=day, prompt=prompt, order=day.option_groups.count(),
                                           kind=ideas.choice_kind(idea))
    option = Option.objects.create(group=group, title=idea.title[:200], notes=idea.notes,
                                   order=(group.options.aggregate(m=Max("order"))["m"] or 0) + 1)
    if group.kind != OptionGroup.Kind.ANY:
        ideas.fill_option(idea, option)
        trip_cities.sync(trip)
    elif idea.target is not None:
        item, *_ = _make_on_day(trip, group.day, parser.parse(idea.title, kind=idea.kind))
        ideas.fill(idea, item)
        item.option = option
        item.save(update_fields=["option"])
        trip_cities.sync(trip)
    idea.place_on(option)
    messages.success(request, f"Added “{idea.title}” as an option of “{group.prompt}”.")
    back = reverse("trips:trip_detail", args=[trip.pk]) + f"#group-{group.pk}"
    return redirect(f"{reverse('trips:group_edit', args=[trip.pk, group.pk])}?next={quote(back)}")


CATALOGUE = {"poi": POI, "city": City, "activity": Activity, "event": Event}


def _catalogue_target(kind, obj_pk, user):
    model = CATALOGUE.get(kind)
    if model is None:
        raise Http404
    obj = get_object_or_404(model, pk=obj_pk)
    visible = (obj.is_visible_to(user) if hasattr(obj, "is_visible_to")
               else obj.approval_status == ApprovalStatus.APPROVED or user.is_staff)
    if not visible:
        raise Http404
    return obj


def commentable_trips(user):
    """The member's trips that aren't over and that they may add ideas to, soonest first."""
    today = timezone.localdate()
    trips = Trip.objects.visible_to(user).filter(end_date__gte=today).order_by("start_date", "name")
    return [trip for trip in trips if trip.can(user, "comment")]


@login_required
def idea_from_catalogue(request, kind, obj_pk):
    """"Add to a trip" from a catalogue page: pick one of your trips; the item joins its Ideas shelf."""
    target = _catalogue_target(kind, obj_pk, request.user)
    trips = commentable_trips(request.user)
    if request.method == "POST":
        trip = next((t for t in trips if str(t.pk) == request.POST.get("trip")), None)
        if trip is None:
            raise Http404
        idea = TripIdea.objects.filter(trip=trip, **{kind: target}).first()
        if idea is None:
            idea = TripIdea.objects.create(trip=trip, title=target.name[:200], added_by=request.user, **{kind: target})
            trip_cities.sync(trip)
            messages.success(request, f"Added “{target.name}” to the ideas for “{trip.name}”.")
        else:
            messages.info(request, f"“{target.name}” is already an idea for “{trip.name}”.")
        return redirect(_shelf(trip, idea))
    return render(request, "trips/idea_from_catalogue.html", {
        "target": target, "kind": kind, "trips": trips, "back": _back(request, ""),
    })
