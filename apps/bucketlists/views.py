# bucketlists/views.py
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.activities.models import Activity
from apps.approval_system.models import ApprovalStatus
from apps.core.utils.breadcrumbs import build_breadcrumbs
from apps.events.models import Event
from apps.locations.models import POI, City
from apps.trips.models import Traveler, Trip, TripGrant, TripRole

from .forms import BucketListItemForm, CategoryForm, CompleteItemForm, PlanTripForm
from .models import BucketListCategory, BucketListItem

ACTIVE_STATUSES = ("researching", "planning", "booked", "in_progress")
SORTS = {"priority": ("-priority", "display_order", "-created_at"), "newest": ("-created_at",),
         "target": ("target_date", "-priority"), "title": ("custom_title",)}


def _target_for(kind, pk, user):
    """The activity / city / POI / event behind a quick-add, if the user may see it."""
    if kind == "activity":
        obj = get_object_or_404(Activity, pk=pk)
        ok = obj.is_visible_to(user)
    elif kind == "event":
        obj = get_object_or_404(Event, pk=pk)
        ok = obj.is_visible_to(user)
    elif kind in ("city", "poi"):
        obj = get_object_or_404(City if kind == "city" else POI, pk=pk)
        ok = obj.approval_status == ApprovalStatus.APPROVED or user.is_staff
    else:
        raise Http404
    if not ok:
        raise Http404
    return obj


def _items():
    """Bucket items with everything the cards and titles touch."""
    return (
        BucketListItem.objects
        .select_related("activity__city", "activity__region", "activity__country", "city__country",
                        "event__city__country", "event__country", "trip")
        .prefetch_related(Prefetch("pois", queryset=POI.objects.select_related("city").order_by("name")))
    )


def _own_item(request, pk):
    return get_object_or_404(_items(), pk=pk, user=request.user)


def _find_or_start(user, kind, target):
    """The user's existing item for ``target``, or an unsaved new one, and whether it exists.

    Adding a dated event of an activity already on the list dates that item
    rather than starting a second one (Oktoberfest -> Oktoberfest 2027).
    """
    mine = BucketListItem.objects.filter(user=user)
    if kind == "poi":
        existing = mine.filter(pois=target).first()
        return (existing, True) if existing else (BucketListItem(user=user), False)
    existing = mine.filter(**{kind: target}).first()
    if existing:
        return existing, True
    if kind == "event" and target.related_activity_id:
        undated = mine.filter(activity_id=target.related_activity_id, event__isnull=True).first()
        if undated:
            undated.event = target
            return undated, False
        return BucketListItem(user=user, activity_id=target.related_activity_id, event=target), False
    return BucketListItem(user=user, **{kind: target}), False


@login_required
def dashboard(request):
    """The user's bucket list, with progress and filters."""
    items = _items().filter(user=request.user).prefetch_related("categories")
    all_items = items
    status = request.GET.get("status", "")
    if status == "active":
        items = items.filter(status__in=ACTIVE_STATUSES)
    elif status:
        items = items.filter(status=status)
    else:
        items = items.exclude(status="abandoned")
    category = request.GET.get("category", "")
    if category:
        items = items.filter(categories__pk=category)
    q = request.GET.get("q", "").strip()
    if q:
        items = items.filter(
            Q(custom_title__icontains=q) | Q(activity__name__icontains=q) | Q(city__name__icontains=q)
            | Q(pois__name__icontains=q) | Q(event__name__icontains=q) | Q(personal_notes__icontains=q)
        )
    sort = request.GET.get("sort", "priority")
    items = items.order_by(*SORTS.get(sort, SORTS["priority"])).distinct()

    counts = all_items.aggregate(
        total=Count("id", filter=~Q(status="abandoned")),
        completed=Count("id", filter=Q(status="completed")),
        active=Count("id", filter=Q(status__in=ACTIVE_STATUSES)),
    )
    counts["percent"] = round(100 * counts["completed"] / counts["total"]) if counts["total"] else 0
    return render(request, "bucketlists/dashboard.html", {
        "items": items,
        "counts": counts,
        "categories": BucketListCategory.objects.filter(user=request.user).annotate(n=Count("items")),
        "status_choices": BucketListItem.STATUS_CHOICES,
        "filters": {"status": status, "category": category, "q": q, "sort": sort},
        "breadcrumb_list": build_breadcrumbs([("Bucket list", None)]),
    })


def _kind_of(item, pois):
    return "poi" if pois else item.kind


@login_required
def item_add(request):
    """Add a custom item, or (with ?activity= / ?city= / ?poi= / ?event=) a linked one."""
    kind = next((k for k in BucketListItem.TARGET_KINDS if request.GET.get(k)), None)
    target = _target_for(kind, request.GET[kind], request.user) if kind else None
    item, pois = BucketListItem(user=request.user), []
    if target is not None:
        item, exists = _find_or_start(request.user, kind, target)
        if exists:
            messages.info(request, f"“{item.title}” is already on your bucket list.")
            return redirect("bucketlists:item_edit", pk=item.pk)
        if item.pk:  # an undated activity item gets this event's date
            item.save(update_fields=["event"])
            messages.success(request, f"“{item.title}” now has a date: {target}.")
            return redirect("bucketlists:item_edit", pk=item.pk)
        pois = [target] if kind == "poi" else []
    form = BucketListItemForm(request.POST or None, instance=item, user=request.user,
                              kind=_kind_of(item, pois), pois=pois)
    if request.method == "POST" and form.is_valid():
        item = form.save()
        messages.success(request, f"Added “{item.title}” to your bucket list.")
        return redirect("bucketlists:dashboard")
    return render(request, "bucketlists/item_form.html", {
        "form": form, "target": target, "kind": kind, "title": "Add to your bucket list",
        "breadcrumb_list": build_breadcrumbs([("Bucket list", "bucketlists:dashboard"), ("Add", None)]),
    })


@login_required
@require_POST
def quick_add(request, kind, pk):
    """One-click add from an activity / city / POI / event page."""
    target = _target_for(kind, pk, request.user)
    item, exists = _find_or_start(request.user, kind, target)
    if exists:
        messages.info(request, f"“{item.title}” is already on your bucket list.")
    else:
        dated = item.pk is not None
        item.save()
        if kind == "poi":
            item.pois.add(target)
        if dated:
            messages.success(request, f"“{item.title}” now has a date: {target}.")
        else:
            messages.success(request, f"Added “{item.title}” to your bucket list. Add a date or notes any time.")
    return redirect("bucketlists:item_edit", pk=item.pk)


@login_required
def item_edit(request, pk):
    item = _own_item(request, pk)
    form = BucketListItemForm(request.POST or None, instance=item, user=request.user, kind=item.kind)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved.")
        return redirect("bucketlists:dashboard")
    return render(request, "bucketlists/item_form.html", {
        "form": form, "item": item, "target": item.target, "kind": item.kind, "title": item.title,
        "breadcrumb_list": build_breadcrumbs([("Bucket list", "bucketlists:dashboard"), (item.title, None)]),
    })


@login_required
def plan_trip(request, pk):
    """Start a trip for a bucket-list item, pre-filled from its dates and place.

    Open to any signed-in user (not only the ``creator`` role): the trip is
    their own plan for their own goal. As in ``trips.views.trip_create`` the
    creator gets an editor grant, which is what lets them open and finish it.
    """
    item = _own_item(request, pk)
    if item.live_trip:
        return redirect("trips:trip_detail", pk=item.trip_id)
    start, end = item.dates
    title = item.title if not start or str(start.year) in item.title else f"{item.title} {start.year}"
    form = PlanTripForm(request.POST or None, initial={
        "name": title, "destination": item.place, "start_date": start, "end_date": end,
    })
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            trip = Trip.objects.create(created_by=request.user, **form.cleaned_data)
            TripGrant.objects.create(trip=trip, user=request.user, granted_by=request.user, role=TripRole.EDITOR)
            traveler = Traveler.objects.filter(user=request.user).first()
            if traveler:
                trip.travelers.add(traveler)
            item.trip = trip
            if item.status in ("wishlist", "researching"):
                item.status = "planning"
            item.save(update_fields=["trip", "status", "updated_at"])
        messages.success(request, f"Started “{trip.name}”. Add flights, lodging and the rest here.")
        return redirect("trips:trip_edit", pk=trip.pk)
    return render(request, "bucketlists/plan_trip.html", {
        "form": form, "item": item,
        "breadcrumb_list": build_breadcrumbs([("Bucket list", "bucketlists:dashboard"),
                                              (item.title, reverse("bucketlists:item_edit", args=[item.pk])), ("Plan a trip", None)]),
    })


SUGGEST_LIMIT = 4


@login_required
def suggest(request):
    """Catalogue matches for a goal's title, as JSON: activities, upcoming events,
    cities and places the user may see. Used to steer "Add a goal" toward a linked
    item, and to link an existing goal."""
    q = request.GET.get("q", "").strip()
    if len(q) < 3:
        return JsonResponse({"results": []})
    add = reverse("bucketlists:item_add")
    results = []
    for a in Activity.get_public_activities().filter(name__icontains=q).select_related("category").order_by("name")[:SUGGEST_LIMIT]:
        results.append({"kind": "activity", "pk": a.pk, "name": a.name, "detail": f"Activity · {a.category.name}"})
    events = (Event.objects.visible_to(request.user).filter(name__icontains=q, start_date__gte=timezone.now().date())
              .select_related("city__country", "country").order_by("start_date")[:SUGGEST_LIMIT])
    for e in events:
        results.append({"kind": "event", "pk": e.pk, "name": e.name,
                        "detail": f"Event · {e.start_date:%b} {e.start_date.day}, {e.start_date.year} · {e.place_name}"})
    approved = {"approval_status": ApprovalStatus.APPROVED, "name__icontains": q}
    for c in City.objects.filter(**approved).select_related("country").order_by("name")[:SUGGEST_LIMIT]:
        results.append({"kind": "city", "pk": c.pk, "name": c.name, "detail": f"City · {c.country.name}"})
    for p in POI.objects.filter(**approved).select_related("city").order_by("name")[:SUGGEST_LIMIT]:
        results.append({"kind": "poi", "pk": p.pk, "name": p.name, "detail": f"Place · {p.city.name}"})
    for r in results:
        r["add_url"] = f"{add}?{r['kind']}={r['pk']}"
    return JsonResponse({"results": results})


@login_required
@require_POST
def link_item(request, pk):
    """Turn a custom goal into a linked one (activity / event / city / POI), keeping
    its notes, dates, status and categories. The free-text description moves into
    the personal notes so nothing typed is lost."""
    item = _own_item(request, pk)
    if item.kind != "custom":
        messages.info(request, "This item is already linked.")
        return redirect("bucketlists:item_edit", pk=item.pk)
    kind, _, target_pk = request.POST.get("target", "").partition(":")
    if kind not in BucketListItem.TARGET_KINDS or not target_pk.isdigit():
        raise Http404
    target = _target_for(kind, int(target_pk), request.user)

    others = BucketListItem.objects.filter(user=request.user).exclude(pk=item.pk)
    if kind == "poi":
        clash = others.filter(pois=target)
    elif kind == "event" and target.related_activity_id:
        clash = others.filter(Q(event=target) | Q(activity_id=target.related_activity_id))
    else:
        clash = others.filter(**{kind: target})
    clash = clash.first()
    if clash:
        messages.error(request, f"“{clash.title}” is already on your bucket list. Edit that one, or remove this goal.")
        return redirect("bucketlists:item_edit", pk=item.pk)

    old_title = item.title
    with transaction.atomic():
        if kind == "event" and target.related_activity_id:
            item.activity_id, item.event = target.related_activity_id, target
        elif kind != "poi":
            setattr(item, kind, target)
        if item.custom_description:
            item.personal_notes = "\n\n".join(x for x in (item.personal_notes, item.custom_description) if x)
            item.custom_description = ""
        if kind != "poi":  # a POI goal keeps its title as the goal's name
            item.custom_title = ""
        item.save()
        if kind == "poi":
            item.pois.add(target)
    messages.success(request, f"Linked “{old_title}” to {target.name}.")
    return redirect("bucketlists:item_edit", pk=item.pk)


OPEN_STATUSES_EXCLUDED = ("completed", "abandoned")


@login_required
def my_dates(request):
    """Lifecycle stage 3, "Pick a date": the user's open goals that have a date
    (soonest first, ready to plan a trip) and those still waiting for one. An
    undated activity goal lists that activity's upcoming events to pick from."""
    today = timezone.now().date()
    items = list(_items().filter(user=request.user).exclude(status__in=OPEN_STATUSES_EXCLUDED))
    dated, past, undated = [], [], []
    for item in items:
        start, end = item.dates
        if item.trip_finished:
            past.append(item)
            continue
        if start is None:
            undated.append(item)
        elif end < today:
            past.append(item)
        else:
            dated.append(item)
    dated.sort(key=lambda i: i.dates[0])
    past.sort(key=lambda i: i.dates[0] or i.live_trip.end_date, reverse=True)
    undated.sort(key=lambda i: (-i.priority, i.title.lower()))

    activity_ids = {i.activity_id for i in undated if i.activity_id}
    options = {}
    for event in (Event.objects.visible_to(request.user)
                  .filter(related_activity_id__in=activity_ids, start_date__gte=today)
                  .select_related("city__country", "country").order_by("start_date")):
        options.setdefault(event.related_activity_id, []).append(event)
    for item in undated:
        item.date_options = options.get(item.activity_id, [])[:3] if item.activity_id else []

    return render(request, "bucketlists/my_dates.html", {
        "dated": dated, "past": past, "undated": undated, "today": today,
        "breadcrumb_list": build_breadcrumbs([("Bucket list", "bucketlists:dashboard"), ("My dates", None)]),
    })


@login_required
@require_POST
def trip_done(request, trip_pk):
    """From a finished trip's page: tick off the goal(s) it was for.

    One open goal -> its "mark done" page. Several -> My dates, where they are
    listed. None (a trip not started from a goal) -> a goal is created for it
    with the trip's dates, then its "mark done" page.
    """
    trip = get_object_or_404(Trip.objects.visible_to(request.user), pk=trip_pk)
    linked = BucketListItem.objects.filter(user=request.user, trip=trip)
    open_items = list(linked.exclude(status__in=OPEN_STATUSES_EXCLUDED))
    if len(open_items) == 1:
        return redirect("bucketlists:item_complete", pk=open_items[0].pk)
    if open_items:
        messages.info(request, f"Several goals are linked to “{trip.name}”. Tick each one off below.")
        return redirect("bucketlists:dates")
    if linked.filter(status="completed").exists():
        messages.info(request, f"“{trip.name}” is already ticked off your bucket list.")
        return redirect(reverse("bucketlists:dashboard") + "?status=completed")
    item = BucketListItem.objects.create(
        user=request.user, custom_title=trip.name, trip=trip, status="in_progress",
        target_date=trip.start_date, target_end_date=trip.end_date,
    )
    messages.info(request, f"Added “{trip.name}” to your bucket list. Add your rating and notes to tick it off.")
    return redirect("bucketlists:item_complete", pk=item.pk)


@login_required
@require_POST
def pick_date(request, pk):
    """Date an activity goal with one of that activity's events (from My dates)."""
    item = _own_item(request, pk)
    event = get_object_or_404(Event.objects.visible_to(request.user), pk=request.POST.get("event") or 0)
    if not item.activity_id or event.related_activity_id != item.activity_id:
        raise Http404
    item.event = event
    item.save()
    messages.success(request, f"“{item.title}” is set for {event.name}, {event.start_date:%b} {event.start_date.day}, {event.start_date.year}.")
    return redirect("bucketlists:dates")


@login_required
def item_complete(request, pk):
    item = _own_item(request, pk)
    form = CompleteItemForm(request.POST or None, initial={
        "completed_date": item.completed_date or timezone.now().date(),
        "user_rating": item.user_rating, "completion_notes": item.completion_notes,
    })
    if request.method == "POST" and form.is_valid():
        item.complete(form.cleaned_data["completed_date"], form.cleaned_data["completion_notes"],
                      form.cleaned_data["user_rating"])
        messages.success(request, f"🎉 Ticked off “{item.title}”!")
        return redirect("bucketlists:dashboard")
    return render(request, "bucketlists/item_complete.html", {"form": form, "item": item})


@login_required
def item_delete(request, pk):
    item = _own_item(request, pk)
    if request.method == "POST":
        title = item.title
        item.delete()
        messages.success(request, f"Removed “{title}” from your bucket list.")
        return redirect("bucketlists:dashboard")
    return render(request, "bucketlists/item_confirm_delete.html", {"item": item})


@login_required
def categories(request):
    """List the user's categories and add new ones."""
    form = CategoryForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        category = form.save(commit=False)
        category.user = request.user
        category.save()
        messages.success(request, f"Added category “{category.name}”.")
        return redirect("bucketlists:categories")
    return render(request, "bucketlists/categories.html", {
        "form": form,
        "categories": BucketListCategory.objects.filter(user=request.user).annotate(n=Count("items")),
        "breadcrumb_list": build_breadcrumbs([("Bucket list", "bucketlists:dashboard"), ("Categories", None)]),
    })


@login_required
def category_edit(request, pk):
    category = get_object_or_404(BucketListCategory, pk=pk, user=request.user)
    form = CategoryForm(request.POST or None, instance=category, user=request.user)
    if request.method == "POST":
        if "delete" in request.POST:
            name = category.name
            category.delete()
            messages.success(request, f"Deleted category “{name}”. Its items are still on your list.")
            return redirect("bucketlists:categories")
        if form.is_valid():
            form.save()
            messages.success(request, "Saved.")
            return redirect("bucketlists:categories")
    return render(request, "bucketlists/category_form.html", {
        "form": form, "category": category,
        "breadcrumb_list": build_breadcrumbs([("Bucket list", "bucketlists:dashboard"), ("Categories", "bucketlists:categories"), (category.name, None)]),
    })


def public_list(request, username):
    """A user's public bucket list. 404 unless their profile is public (or it's yours)."""
    owner = get_object_or_404(get_user_model(), username=username, is_active=True)
    is_owner = request.user.is_authenticated and request.user == owner
    if not is_owner and owner.profile_visibility != "public":
        raise Http404
    items = (
        _items().filter(user=owner, is_public=True).exclude(status="abandoned")
        .order_by("status", "-priority", "-completed_date")
    )
    done = [i for i in items if i.status == "completed"]
    todo = [i for i in items if i.status != "completed"]
    return render(request, "bucketlists/public_list.html", {
        "owner": owner, "todo": todo, "done": done, "is_owner": is_owner,
    })
