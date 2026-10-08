# bucketlists/views.py
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.activities.models import Activity
from apps.approval_system.models import ApprovalStatus
from apps.core.utils.breadcrumbs import build_breadcrumbs
from apps.events.models import Event
from apps.locations.models import POI, City

from .forms import BucketListItemForm, CategoryForm, CompleteItemForm
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


def _own_item(request, pk):
    return get_object_or_404(
        BucketListItem.objects.select_related("activity", "city__country", "poi__city", "event"),
        pk=pk, user=request.user,
    )


@login_required
def dashboard(request):
    """The user's bucket list, with progress and filters."""
    items = (
        BucketListItem.objects.filter(user=request.user)
        .select_related("activity", "city__country", "poi__city", "event")
        .prefetch_related("categories")
    )
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
            | Q(poi__name__icontains=q) | Q(event__name__icontains=q) | Q(personal_notes__icontains=q)
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


@login_required
def item_add(request):
    """Add a custom item, or (with ?activity= / ?city= / ?poi= / ?event=) a linked one."""
    kind = next((k for k in BucketListItem.TARGET_KINDS if request.GET.get(k)), None)
    target = _target_for(kind, request.GET[kind], request.user) if kind else None
    if target is not None:
        existing = BucketListItem.objects.filter(user=request.user, **{kind: target}).first()
        if existing:
            messages.info(request, f"“{existing.title}” is already on your bucket list.")
            return redirect("bucketlists:item_edit", pk=existing.pk)
    form = BucketListItemForm(request.POST or None, user=request.user, linked=target is not None)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.user = request.user
        if target is not None:
            setattr(item, kind, target)
        item.save()
        form.save_m2m()
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
    item, created = BucketListItem.objects.get_or_create(user=request.user, **{kind: target})
    if created:
        messages.success(request, f"Added “{item.title}” to your bucket list. Add a date or notes any time.")
    else:
        messages.info(request, f"“{item.title}” is already on your bucket list.")
    return redirect("bucketlists:item_edit", pk=item.pk)


@login_required
def item_edit(request, pk):
    item = _own_item(request, pk)
    form = BucketListItemForm(request.POST or None, instance=item, user=request.user, linked=item.kind != "custom")
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved.")
        return redirect("bucketlists:dashboard")
    return render(request, "bucketlists/item_form.html", {
        "form": form, "item": item, "target": item.target, "kind": item.kind, "title": item.title,
        "breadcrumb_list": build_breadcrumbs([("Bucket list", "bucketlists:dashboard"), (item.title, None)]),
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
        BucketListItem.objects.filter(user=owner, is_public=True).exclude(status="abandoned")
        .select_related("activity", "city__country", "poi__city", "event")
        .order_by("status", "-priority", "-completed_date")
    )
    done = [i for i in items if i.status == "completed"]
    todo = [i for i in items if i.status != "completed"]
    return render(request, "bucketlists/public_list.html", {
        "owner": owner, "todo": todo, "done": done, "is_owner": is_owner,
    })
