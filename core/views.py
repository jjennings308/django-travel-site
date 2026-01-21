# core/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta
from accounts.models import User, Profile
from trips.models import Trip
from bucketlists.models import BucketListItem
# from activities.models import Activity  # Uncomment when ready
# from recommendations.models import Recommendation  # When you create this


def home(request):
    """Pre-login home page"""
    # Redirect authenticated users to dashboard
    if request.user.is_authenticated:
        return redirect('core:dashboard')
    
    # Stats for homepage
    context = {
        'total_users': User.objects.filter(is_active=True).count(),
        'total_trips': Trip.objects.count(),
        'countries_count': Profile.objects.exclude(
            home_country__isnull=True
        ).values('home_country').distinct().count(),
    }
    return render(request, 'home.html', context)


@login_required
def dashboard(request):
    """Post-login dashboard with personalized content"""
    user = request.user
    
    # Quick stats for header
    bucket_list_count = BucketListItem.objects.filter(user=user).count()
    trips_count = Trip.objects.filter(user=user).count()
    
    # Countries visited - from completed trips
    countries_visited = Trip.objects.filter(
        user=user,
        status='completed'
    ).values('countries').distinct().count()
    
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
    recent_trips = Trip.objects.filter(
        user=user
    ).order_by('-created_at')[:3]
    
    for trip in recent_trips:
        recent_activities.append({
            'title': 'Created Trip',
            'description': trip.title,
            'created_at': trip.created_at,
            'icon': 'bi-airplane',
            'color_class': '#2563eb',  # Primary color
        })
    
    # Sort all activities by date
    recent_activities.sort(key=lambda x: x['created_at'], reverse=True)
    recent_activities = recent_activities[:5]  # Keep only 5 most recent
    
    # Upcoming Trips
    today = timezone.now().date()
    upcoming_trips = Trip.objects.filter(
        user=user,
        start_date__gte=today,
        status__in=['planning', 'booked']  # Only show active upcoming trips
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
    
    # Recommendations (placeholder - you'll build this system later)
    # For now, using static examples
    recommendations = [
        {
            'tag': 'Popular',
            'title': 'Explore Paris',
            'description': 'The city of lights awaits with amazing food, culture, and iconic landmarks.',
            'image_url': 'https://images.unsplash.com/photo-1502602898657-3e91760cbb34?w=300&h=200&fit=crop',
            'url': '#',
        },
        {
            'tag': 'Trending',
            'title': 'Bali Adventure',
            'description': 'Discover pristine beaches, ancient temples, and vibrant culture.',
            'image_url': 'https://images.unsplash.com/photo-1537996194471-e657df975ab4?w=300&h=200&fit=crop',
            'url': '#',
        },
    ]
    
    # Later, replace with:
    # recommendations = Recommendation.objects.get_for_user(user)[:3]
    
    context = {
        'recent_activities': recent_activities,
        'upcoming_trips': upcoming_trips,
        'bucket_list_stats': bucket_list_stats,
        'recommendations': recommendations,
    }
    
    return render(request, 'core/dashboard.html', context)


def about(request):
    """About page"""
    return render(request, 'core/about.html')