# bucketlists/views.py
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import Http404
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
        .select_related("activity", "city__country", "event__city__country", "event__country", "trip")
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
