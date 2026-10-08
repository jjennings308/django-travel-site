# events/views.py
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.core.utils.breadcrumbs import build_breadcrumbs
from apps.locations.models import City, Country

from .forms import EventForm
from .models import Event


def _visible_event_or_404(request, slug):
    """404 (not 403) for an event this user may not see, so its existence isn't revealed."""
    event = get_object_or_404(
        Event.objects.select_related("category", "city__country", "country", "poi", "created_by", "related_activity"), slug=slug
    )
    if not event.is_visible_to(request.user):
        raise Http404
    return event


def event_list(request):
    """Browse approved events (upcoming by default), with filters."""
    today = timezone.now().date()
    events = (
        Event.objects.filter(approval_status=ApprovalStatus.APPROVED)
        .select_related("category", "city__country", "country")
    )
    when = request.GET.get("when", "upcoming")
    if when == "past":
        events = events.filter(end_date__lt=today).order_by("-start_date")
    else:
        when = "upcoming"
        events = events.filter(end_date__gte=today).order_by("start_date", "start_time")

    activity = None
    if request.GET.get("activity"):
        activity = get_object_or_404(Activity.get_public_activities(), slug=request.GET["activity"])
        events = events.filter(related_activity=activity)
    category = request.GET.get("category")
    if category:
        events = events.filter(category__slug=category)
    country = request.GET.get("country")
    if country:
        events = events.filter(Q(city__country__slug=country) | Q(country__slug=country))
    if request.GET.get("free"):
        events = events.filter(is_free=True)
    q = request.GET.get("q", "").strip()
    if q:
        events = events.filter(
            Q(name__icontains=q) | Q(short_description__icontains=q) | Q(description__icontains=q)
            | Q(city__name__icontains=q) | Q(location_text__icontains=q) | Q(venue_name__icontains=q)
        )

    page_obj = Paginator(events, 24).get_page(request.GET.get("page"))
    countries = Country.objects.filter(
        Q(cities__events__approval_status=ApprovalStatus.APPROVED)
        | Q(events_unlinked__approval_status=ApprovalStatus.APPROVED)
    ).distinct().order_by("name")
    return render(request, "events/event_list.html", {
        "page_obj": page_obj,
        "categories": ActivityCategory.objects.filter(is_active=True),
        "countries": countries,
        "when": when,
        "activity": activity,
        "filters": {"category": category or "", "country": country or "", "free": bool(request.GET.get("free")), "q": q},
        "breadcrumb_list": build_breadcrumbs([("Events", None)]),
    })


def event_detail(request, slug):
    event = _visible_event_or_404(request, slug)
    return render(request, "events/event_detail.html", {
        "event": event,
        "performers": event.performers.all(),
        "can_edit": event.can_edit(request.user),
        "can_delete": event.can_delete(request.user),
        "city_choices": (
            City.objects.filter(country=event.country, approval_status=ApprovalStatus.APPROVED).order_by("name")
            if request.user.is_staff and event.needs_city_link and event.country_id else None
        ),
        "breadcrumb_list": build_breadcrumbs([("Events", "events:event_list"), (event.name, None)]),
    })


@login_required
def my_events(request):
    """Everything the user submitted, at any approval stage."""
    events = Event.objects.filter(created_by=request.user).select_related("category", "city__country", "country").order_by("-start_date")
    return render(request, "events/my_events.html", {
        "events": events,
        "breadcrumb_list": build_breadcrumbs([("Events", "events:event_list"), ("My events", None)]),
    })


@login_required
def event_add(request):
    initial = {}
    if request.GET.get("activity"):
        # "Add a date" from an activity page: pre-fill from the activity.
        activity = Activity.get_public_activities().filter(pk=request.GET["activity"]).first()
        if activity:
            initial = {"related_activity": activity, "name": activity.name, "category": activity.category,
                       "short_description": activity.short_description, "description": activity.description}
    form = EventForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        event = form.save(commit=False)
        event.created_by = request.user
        if request.user.is_staff:
            event.approval_status = ApprovalStatus.APPROVED
            event.save()
            messages.success(request, f"“{event.name}” is published.")
        else:
            event.save()
            event.submit_for_review(request.user)
            messages.success(request, f"Thanks! “{event.name}” was sent for review. Only you can see it until it's approved.")
        return redirect("events:event_detail", slug=event.slug)
    return render(request, "events/event_form.html", {
        "form": form, "title": "Add an event",
        "breadcrumb_list": build_breadcrumbs([("Events", "events:event_list"), ("Add", None)]),
    })


@login_required
def event_edit(request, slug):
    event = _visible_event_or_404(request, slug)
    if not event.can_edit(request.user):
        messages.error(request, "Approved events can only be changed by staff.")
        return redirect("events:event_detail", slug=slug)
    form = EventForm(request.POST or None, instance=event)
    if request.method == "POST" and form.is_valid():
        event = form.save()
        # A creator's edit of a rejected / changes-requested event goes back to the queue.
        if not request.user.is_staff and event.approval_status in (
            ApprovalStatus.REJECTED, ApprovalStatus.CHANGES_REQUESTED, ApprovalStatus.DRAFT
        ):
            event.submit_for_review(request.user)
            messages.success(request, "Saved and re-submitted for review.")
        else:
            messages.success(request, "Saved.")
        return redirect("events:event_detail", slug=event.slug)
    return render(request, "events/event_form.html", {
        "form": form, "event": event, "title": f"Edit: {event.name}",
        "breadcrumb_list": build_breadcrumbs([("Events", "events:event_list"), (event.name, ("events:event_detail", {"slug": event.slug})), ("Edit", None)]),
    })


@login_required
def event_delete(request, slug):
    event = _visible_event_or_404(request, slug)
    if not event.can_delete(request.user):
        messages.error(request, "Approved events can only be removed by staff.")
        return redirect("events:event_detail", slug=slug)
    if request.method == "POST":
        name = event.name
        event.delete()
        messages.success(request, f"Deleted “{name}”.")
        return redirect("events:my_events")
    return render(request, "events/event_confirm_delete.html", {"event": event})


@staff_member_required
@require_POST
def event_link_city(request, slug):
    """Staff: attach a typed (unlisted) location to a catalogue city, either an
    existing city or a new one created here (approved, since staff create it)."""
    event = get_object_or_404(Event, slug=slug)
    if not event.needs_city_link:
        messages.info(request, "This event is already linked to a city.")
        return redirect("events:event_detail", slug=slug)
    if request.POST.get("city"):
        city = get_object_or_404(City, pk=request.POST["city"], approval_status=ApprovalStatus.APPROVED)
    else:
        name = (request.POST.get("name") or "").strip()
        try:
            lat = float(request.POST.get("latitude", ""))
            lng = float(request.POST.get("longitude", ""))
        except ValueError:
            lat = lng = None
        if not name or lat is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
            messages.error(request, "To create the city, give its name and valid latitude/longitude.")
            return redirect("events:event_detail", slug=slug)
        existing = City.objects.filter(country=event.country, name__iexact=name).first()
        if existing:
            city = existing
        else:
            now = timezone.now()
            city = City.objects.create(
                name=name, country=event.country, latitude=lat, longitude=lng,
                approval_status=ApprovalStatus.APPROVED, submitted_by=event.created_by or request.user,
                submitted_at=now, reviewed_by=request.user, reviewed_at=now,
            )
            messages.success(request, f"Created the city {city.name}, {city.country.name}.")
    event.city = city
    event.save()
    messages.success(request, f"Linked the event to {city.name}, {city.country.name}.")
    return redirect("events:event_detail", slug=slug)

