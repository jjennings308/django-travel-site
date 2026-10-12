# pages/views.py
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.shortcuts import render, redirect
from django.db.models import Count, Q
from django.utils import timezone
from django.contrib import messages
from django.core.cache import cache
from django.core.mail import EmailMessage
from apps.approval_system.models import ApprovalStatus
from datetime import timedelta
from apps.accounts.models import Profile
from apps.trips.models import Trip
from apps.bucketlists.models import BucketListItem
from apps.recommendations.services import Goals, for_user as recommend


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
        "status", "activity_id", "activity__category_id", "activity__country_id", "event_id",
        "event__category_id", "event__city__country_id", "event__country_id", "city__country_id")
    for row in items:
        if row["activity_id"]:
            goals.activity_ids.add(row["activity_id"])
            goals.category_ids.add(row["activity__category_id"])
            if not row["event_id"] and row["status"] not in ("completed", "abandoned"):
                goals.undated_activity_ids.add(row["activity_id"])
        if row["event_id"]:
            goals.event_ids.add(row["event_id"])
            goals.category_ids.add(row["event__category_id"])
        goals.country_ids.update(c for c in (row["activity__country_id"], row["event__city__country_id"],
                                             row["event__country_id"], row["city__country_id"]) if c)
    goals.country_ids.update(c for c in BucketListItem.objects.filter(user=user).values_list("pois__city__country_id", flat=True) if c)
    # ... and the countries of the user's own upcoming trips' cities.
    goals.country_ids.update(c for c in Trip.objects.live().filter(grants__user=user, end_date__gte=timezone.localdate())
                             .values_list("cities__country_id", flat=True) if c)
    return goals


def home(request):
    """Pre-login home page"""
    # Redirect authenticated users to dashboard
    if request.user.is_authenticated:
        return redirect('pages:dashboard')
    context = {"catalogue": _catalogue_counts()}
    return render(request, 'pages/home.html', context)


@login_required
def dashboard(request):
    """Post-login dashboard with personalized content"""
    user = request.user
    
    # Quick stats for header
    bucket_list_count = BucketListItem.objects.filter(user=user).count()
    # Trip access goes through visible_to: grants plus the role ladder.
    visible_trips = Trip.objects.visible_to(user)
    trips_count = visible_trips.count()
    
    # Destinations of trips that have ended. Trip.destination is free text
    # until it becomes a locations FK (work plan, Phase 4).
    today = timezone.now().date()
    countries_visited = visible_trips.filter(
        end_date__lt=today
    ).exclude(destination='').values('destination').distinct().count()
    
    # Attach counts to user object for template
    user.bucket_list_items_count = bucket_list_count
    user.trips_count = trips_count
    user.countries_visited = countries_visited
    
    # Recent Activity - combine different model activities
    recent_activities = []
    
    # Recent bucket list additions
    recent_bucket_items = BucketListItem.objects.filter(
        user=user
    ).select_related('activity', 'city', 'event').order_by('-created_at')[:3]
    
    for item in recent_bucket_items:
        recent_activities.append({
            'title': 'Added to Bucket List',
            'description': item.title,  # Uses the @property from model
            'created_at': item.created_at,
            'icon': 'bi-check2-square',
            'color_class': '#f59e0b',  # Accent color
        })
    
    # Recent trips
    recent_trips = visible_trips.order_by('-created_at')[:3]
    
    for trip in recent_trips:
        recent_activities.append({
            'title': 'Created Trip',
            'description': trip.name,
            'created_at': trip.created_at,
            'icon': 'bi-airplane',
            'color_class': '#2563eb',  # Primary color
        })
    
    # Sort all activities by date
    recent_activities.sort(key=lambda x: x['created_at'], reverse=True)
    recent_activities = recent_activities[:5]  # Keep only 5 most recent
    
    # Upcoming Trips
    upcoming_trips = visible_trips.filter(
        start_date__gte=today
    ).order_by('start_date')[:3]
    
    # Add days_until for each trip
    for trip in upcoming_trips:
        trip.days_until = (trip.start_date - today).days
    
    # Bucket List Stats
    bucket_list_items = BucketListItem.objects.filter(user=user)
    total_items = bucket_list_items.count()
    
    if total_items > 0:
        completed_items = bucket_list_items.filter(status='completed').count()
        in_progress_items = bucket_list_items.filter(status__in=['planning', 'booked', 'in_progress']).count()
        
        completion_percentage = int((completed_items / total_items) * 100)
        
        bucket_list_stats = {
            'total': total_items,
            'completed': completed_items,
            'in_progress': in_progress_items,
            'completion_percentage': completion_percentage,
        }
    else:
        bucket_list_stats = None
    
    recommendations = recommend(_goals(user))
    from apps.bucketlists.badges import progress
    badges = progress(user)

    context = {
        'recent_activities': recent_activities,
        'upcoming_trips': upcoming_trips,
        'bucket_list_stats': bucket_list_stats,
        'recommendations': recommendations,
        'badges': badges,
        'badges_earned': sum(1 for _, earned_at, _, _ in badges if earned_at),
    }
    
    return render(request, 'pages/dashboard.html', context)


def about(request):
    """About page"""
    return render(request, 'pages/about.html')


def _legal_page(request, template, title):
    """Render one of the legal pages with the details from settings.LEGAL."""
    legal = dict(settings.LEGAL)
    legal["is_draft"] = any(str(v).startswith("[") for v in legal.values())
    return render(request, template, {"legal": legal, "page_title": title})


def terms(request):
    """Terms of Service."""
    return _legal_page(request, "pages/legal/terms.html", "Terms of Service")


def privacy(request):
    """Privacy Policy."""
    return _legal_page(request, "pages/legal/privacy.html", "Privacy Policy")


def safety(request):
    """Safety guidance for travellers and for using the site."""
    return _legal_page(request, "pages/legal/safety.html", "Safety")



CONTACT_LIMIT = 3          # messages per session ...
CONTACT_WINDOW = 60 * 60   # ... per hour


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
                from_email=settings.DEFAULT_FROM_EMAIL, to=[to], reply_to=[data["email"]],
            ).send()
            request.session["contact_sent"] = sent + [now]
        messages.success(request, "Thanks, your message was sent. We'll reply by email.")
        return redirect("pages:contact")
    return render(request, "pages/contact.html", {"form": form, "ready": ready})


def features(request):
    """What the site does, step by step (the footer's Features link; open to everyone)."""
    return render(request, "pages/features.html", {"catalogue": _catalogue_counts()})


def help_page(request):
    """Short how-it-works / FAQ page."""
    return render(request, "pages/help.html")
