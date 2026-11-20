from datetime import date as date_cls

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.db.models import Count, F, Q
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.approval_system.models import ApprovalStatus
from apps.bucketlists.models import BucketListItem
from apps.core.ratelimit import limit
from apps.recommendations.services import Goals
from apps.recommendations.services import for_user as recommend
from apps.trips.models import Trip


def _catalogue_counts():
    """Published catalogue sizes for the home page's stats band, cached for an hour."""
    counts = cache.get("home_catalogue_counts")
    if counts is None:
        from apps.activities.models import Activity
        from apps.locations.models import POI, City, Country

        approved = {"approval_status": ApprovalStatus.APPROVED}
        counts = {
            "countries": Country.objects.filter(**approved).count(),
            "cities": City.objects.filter(**approved).count(),
            "places": POI.objects.filter(**approved).count(),
            "activities": Activity.get_public_activities().count(),
        }
        cache.set("home_catalogue_counts", counts, 60 * 60)
    return counts


def _goals(user):
    """What the user's bucket list covers, for recommendations (ids only, two queries)."""
    goals = Goals()
    items = BucketListItem.objects.filter(user=user).values(
        "status",
        "activity_id",
        "activity__category_id",
        "activity__country_id",
        "event_id",
        "event__category_id",
        "event__city__country_id",
        "event__country_id",
        "city__country_id",
    )
    for row in items:
        if row["activity_id"]:
            goals.activity_ids.add(row["activity_id"])
            goals.category_ids.add(row["activity__category_id"])
            if not row["event_id"] and row["status"] not in ("completed", "abandoned"):
                goals.undated_activity_ids.add(row["activity_id"])
        if row["event_id"]:
            goals.event_ids.add(row["event_id"])
            goals.category_ids.add(row["event__category_id"])
        goals.country_ids.update(
            c
            for c in (
                row["activity__country_id"],
                row["event__city__country_id"],
                row["event__country_id"],
                row["city__country_id"],
            )
            if c
        )
    goals.country_ids.update(
        c for c in BucketListItem.objects.filter(user=user).values_list("pois__city__country_id", flat=True) if c
    )
    # ... and the countries of the user's own upcoming trips' cities.
    goals.country_ids.update(
        c
        for c in Trip.objects.live()
        .filter(grants__user=user, end_date__gte=timezone.localdate())
        .values_list("cities__country_id", flat=True)
        if c
    )
    return goals


def home(request):
    """Pre-login home page"""
    # Redirect authenticated users to dashboard
    if request.user.is_authenticated:
        return redirect("pages:dashboard")
    context = {"catalogue": _catalogue_counts()}
    return render(request, "pages/home.html", context)


@login_required
def dashboard(request):
    """Home (ux-consistency V5): a greeting, then three cards — the next trip, the bucket list and what needs the
    member — then recommendations and badges. A fixed number of queries, whatever the member has
    (``test_dashboard.QueryCountTests``)."""
    user = request.user
    today = timezone.localdate()
    hour = timezone.localtime().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"

    visible_trips = Trip.objects.visible_to(user)
    trips_count = visible_trips.count()
    goals = BucketListItem.objects.filter(user=user)
    goal_counts = goals.aggregate(total=Count("pk"), done=Count("pk", filter=Q(status="completed")))

    recommendations = recommend(_goals(user))
    from apps.bucketlists.badges import progress

    badges = progress(user)

    context = {
        "greeting": f"{greeting}, {user.get_full_name() or user.username}",
        "today": today,
        "welcome": _welcome(user, goal_counts["total"], trips_count),
        "next_trip": _next_trip(visible_trips, today),
        "bucket": _bucket_card(goals, goal_counts),
        "needs_you": _needs_you(user, visible_trips, today),
        "recommendations": recommendations,
        "badges": badges,
        "badges_earned": sum(1 for _, earned_at, _, _ in badges if earned_at),
    }
    return render(request, "pages/dashboard.html", context)


def _next_trip(visible_trips, today):
    """The member's next (or current) trip with its countdown, cities and how many of its to-dos are done."""
    trip = (
        visible_trips.filter(start_date__isnull=False, end_date__gte=today)
        .annotate(
            tasks_total=Count("booking_tasks", distinct=True),
            tasks_done=Count("booking_tasks", filter=Q(booking_tasks__done=True), distinct=True),
        )
        .order_by("start_date", "pk")
        .first()
    )
    if trip is None:
        return None
    trip.days_until = (trip.start_date - today).days
    trip.day_now = (today - trip.start_date).days + 1 if trip.days_until <= 0 else None
    trip.city_names = [city.name for city in trip.cities.all()[:4]]
    trip.tasks_percent = round(100 * trip.tasks_done / trip.tasks_total) if trip.tasks_total else None
    trip.more_upcoming = visible_trips.filter(start_date__gt=trip.start_date).count()
    return trip


def _bucket_card(goals, counts):
    """Done of total and three open goals, the most recently touched first."""
    open_goals = (
        goals.exclude(status__in=("completed", "abandoned"))
        .select_related("activity", "city", "event", "trip")
        .prefetch_related("pois")
        .order_by("-updated_at")[:3]
    )
    total, done = counts["total"], counts["done"]
    return {
        "total": total,
        "done": done,
        "percent": round(100 * done / total) if total else 0,
        "goals": list(open_goals) if total else [],
    }


#: What a member submitted that came back to them (ux-consistency V5), newest decision first; one query each.
SENT_BACK = (ApprovalStatus.CHANGES_REQUESTED, ApprovalStatus.REJECTED)
SENT_BACK_DAYS = 90


def _needs_you(user, visible_trips, today):
    """Open to-dos on trips that haven't ended (most pressing first), finished trips waiting for a rating and the
    member's submissions sent back in the last 90 days."""
    from datetime import timedelta

    from django.urls import reverse

    from apps.activities.models import Activity
    from apps.events.models import Event
    from apps.locations.models import POI, City
    from apps.reviews.models import TripRatingPrompt
    from apps.trips.models import BookingTask

    tasks = BookingTask.objects.filter(done=False, trip__in=visible_trips.filter(end_date__gte=today)).select_related(
        "trip"
    )
    task_count = tasks.count()
    todos = list(tasks.order_by("priority", F("due").asc(nulls_last=True), "trip__start_date", "pk")[:5])
    for task in todos:
        task.url = reverse("trips:trip_todo", args=[task.trip_id])

    ratings = list(
        TripRatingPrompt.objects.filter(
            user=user, answered_at__isnull=True, skipped_at__isnull=True, trip__deleted_at__isnull=True
        )
        .select_related("trip")
        .order_by("-trip__end_date")[:3]
    )
    for prompt in ratings:
        prompt.url = reverse("reviews:trip_rate", args=[prompt.trip_id])

    since = timezone.now() - timedelta(days=SENT_BACK_DAYS)
    sent_back = []
    for model, kind, url_name in (
        (Activity, "Activity", "activities:activity_detail"),
        (Event, "Event", "events:event_detail"),
        (City, "City", "locations:city_detail"),
        (POI, "Place", "locations:poi_detail"),
    ):
        mine = Q(submitted_by=user)
        if any(field.name == "created_by" for field in model._meta.get_fields()):
            mine |= Q(created_by=user)
        for obj in model.objects.filter(mine, approval_status__in=SENT_BACK, reviewed_at__gte=since).only(
            "pk", "name", "slug", "approval_status", "reviewed_at"
        )[:5]:
            sent_back.append(
                {
                    "kind": kind,
                    "name": obj.name,
                    "status": obj.get_approval_status_display(),
                    "rejected": obj.approval_status == ApprovalStatus.REJECTED,
                    "url": reverse(url_name, args=[obj.slug]),
                    "at": obj.reviewed_at,
                }
            )
    sent_back.sort(key=lambda row: row["at"], reverse=True)
    return {
        "todos": todos,
        "todo_count": task_count,
        "ratings": ratings,
        "sent_back": sent_back[:5],
        "any": bool(todos or ratings or sent_back),
    }


def _welcome(user, goals, trips):
    """The first-run welcome's steps (site roadmap R14), or None once dismissed or all done."""
    if user.welcome_dismissed_at:
        return None
    from apps.trips.models import TripInvite

    # Their trips first, then everyone on them (counting on the same join would count only them).
    theirs = Trip.objects.filter(grants__user=user).values("pk")
    invited = (
        Trip.objects.filter(pk__in=theirs).annotate(people=Count("grants")).filter(people__gt=1).exists()
        or TripInvite.objects.filter(invited_by=user).exists()
    )
    steps = [
        {
            "done": goals > 0,
            "title": "Add a goal",
            "text": "Something you want to do or see, someday.",
            "url": "bucketlists:item_add",
            "help": "bucket-list",
        },
        {
            "done": trips > 0,
            "title": "Start a trip",
            "text": "Plan one from a goal, or start one from scratch.",
            "url": "trips:trip_create",
            "help": "starting-a-trip",
        },
        {
            "done": invited,
            "title": "Invite someone",
            "text": "Open a trip, click People, and invite who's going.",
            "url": "trips:trip_list",
            "help": "sharing-and-access",
        },
    ]
    return None if all(step["done"] for step in steps) else steps


@login_required
def welcome_dismiss(request):
    if request.method == "POST":
        request.user.welcome_dismissed_at = timezone.now()
        request.user.save(update_fields=["welcome_dismissed_at"])
    return redirect("pages:dashboard")


def about(request):
    """About page: what the site is for and how it works, with the real catalogue counts."""
    return render(request, "pages/about.html", {"catalogue": _catalogue_counts()})


def _legal_page(request, template, title, version=""):
    """Render one of the legal pages with the details from settings.LEGAL (and its version, R16)."""
    legal = dict(settings.LEGAL)
    legal["is_draft"] = any(str(v).startswith("[") for v in legal.values())
    legal["version"] = version
    return render(request, template, {"legal": legal, "page_title": title})


def terms(request):
    """Terms of Service."""
    return _legal_page(request, "pages/legal/terms.html", "Terms of Service", settings.TERMS_VERSION)


def privacy(request):
    """Privacy Policy."""
    return _legal_page(request, "pages/legal/privacy.html", "Privacy Policy", settings.PRIVACY_VERSION)


def safety(request):
    """Safety guidance for travellers and for using the site."""
    return _legal_page(request, "pages/legal/safety.html", "Safety")


CONTACT_LIMIT = 3  # messages per session ...
CONTACT_WINDOW = 60 * 60  # ... per hour


def contact(request):
    """Contact form: emails settings.LEGAL["contact_email"], Reply-To the sender.

    Disabled (with a note) while the address is still a placeholder. A hidden
    "website" field catches simple bots, and a session can send 3 an hour.
    """
    from .forms import ContactForm

    to = str(settings.LEGAL.get("contact_email", ""))
    ready = bool(to) and not to.startswith("[")
    initial = {}
    if request.user.is_authenticated:
        initial = {"name": request.user.get_full_name() or request.user.username, "email": request.user.email}
    form = ContactForm(request.POST or None, initial=initial)
    if request.method == "POST" and ready and form.is_valid():
        now = timezone.now().timestamp()
        sent = [t for t in request.session.get("contact_sent", []) if now - t < CONTACT_WINDOW]
        if form.cleaned_data["website"]:
            pass  # a bot filled the hidden field: pretend it worked, send nothing
        elif len(sent) >= CONTACT_LIMIT:
            messages.error(request, "You've sent several messages already. Please try again in an hour.")
            return redirect("pages:contact")
        else:
            data = form.cleaned_data
            EmailMessage(
                subject=f"[{settings.SITE_NAME} contact] {data['subject']}",
                body=f"From: {data['name']} <{data['email']}>\n"
                f"Signed in as: {request.user.username if request.user.is_authenticated else '(not signed in)'}\n\n"
                f"{data['message']}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[to],
                reply_to=[data["email"]],
            ).send()
            request.session["contact_sent"] = sent + [now]
        messages.success(request, "Thanks, your message was sent. We'll reply by email.")
        return redirect("pages:contact")
    return render(request, "pages/contact.html", {"form": form, "ready": ready})


def features(request):
    """What the site does, step by step (the footer's Features link; open to everyone)."""
    return render(request, "pages/features.html", {"catalogue": _catalogue_counts()})


def help_page(request):
    """How it works, the FAQ, and the guides the reader may see, grouped by section (helpdocs)."""
    from . import helpdocs

    return render(request, "pages/help.html", {"guide_sections": helpdocs.grouped(request.user)})


def help_guide(request, slug):
    """One guide (apps/pages/help/<slug>.md). An unknown slug, or a staff guide for anyone but
    staff, is a 404."""
    from django.http import Http404

    from apps.core.utils.breadcrumbs import build_breadcrumbs

    from . import helpdocs

    guide = helpdocs.guide(slug)
    if guide is None or not helpdocs.is_visible(guide, request.user):
        raise Http404
    related = [g for g in helpdocs.visible_to(request.user) if g.section == guide.section and g.slug != guide.slug]
    return render(
        request,
        "pages/help_guide.html",
        {
            "guide": guide,
            "related": related,
            "show_toc": len(guide.toc) >= 3,
            "breadcrumb_list": build_breadcrumbs([("Help", "pages:help"), (guide.title, None)]),
        },
    )


@limit("search", 120, 60, methods=("GET",))
def search(request):
    """One search over the published catalogue (site roadmap R20; apps/pages/search.py). Grouped by
    kind, up to 8 each; ``?kind=`` shows one kind, paginated. Open to everyone."""
    from django.core.paginator import Paginator

    from apps.core.utils.breadcrumbs import build_breadcrumbs

    from . import search as catalogue_search

    q = request.GET.get("q", "").strip()[:100]
    filters = catalogue_search.Filters.from_get(request.GET)
    context = {
        "search_q": q,
        "filters": filters,
        "kinds": catalogue_search.KINDS,
        "kind_heading": catalogue_search.KINDS.get(filters.kind, ""),
        "months": [(n, date_cls(2000, n, 1).strftime("%B")) for n in range(1, 13)],
        "narrowed": bool(filters.month or filters.category or filters.tag),
        "breadcrumb_list": build_breadcrumbs([("Search", None)]),
        **catalogue_search.filter_choices(filters),
    }
    if len(q) >= 2:
        if filters.kind:
            querysets = catalogue_search.results(filters.kind, q, request.user, filters)
            if len(querysets) == 1:
                context["page_obj"] = Paginator(querysets[0], 24).get_page(request.GET.get("page"))
            else:  # areas: countries then regions, a short list
                items = catalogue_search.areas([obj for qs in querysets for obj in qs[:50]])
                context["page_obj"] = Paginator(items, 24).get_page(request.GET.get("page"))
        else:
            context["groups"] = catalogue_search.grouped(q, request.user, filters)
    return render(request, "pages/search.html", context)


def profile_activity(request, username):
    """A member's recent activity, for their profile page's Recent Activity box (loaded after the page,
    ``partials/_profile_activity.html``; apps/pages/activity_feed.py). Same gate as the profile: a
    private profile, or one waiting to be deleted, is only for its owner (404 otherwise)."""
    from django.http import Http404
    from django.shortcuts import get_object_or_404

    from .activity_feed import feed

    owner = get_object_or_404(get_user_model(), username=username, is_active=True)
    own = request.user.is_authenticated and request.user.pk == owner.pk
    if not own and (owner.profile_visibility == "private" or owner.deletion_requested_at):
        raise Http404
    return render(
        request, "pages/_profile_activity.html", {"entries": feed(owner, request.user), "own": own, "owner": owner}
    )
