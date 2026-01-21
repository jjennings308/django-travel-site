# core/view.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from accounts.models import User, Profile
from trips.models import Trip

def home(request):
    # Redirect authenticated users to dashboard
    if request.user.is_authenticated:
        return redirect('dashboard')  # or your post-login page
    
    context = {
    'total_users': User.objects.filter(is_active=True).count(),
    'total_trips': Trip.objects.count(),
    'countries_count': Profile.objects.values('home_country').distinct().count(),
    }
    return render(request, 'home.html', context)

def core_home(request):
    return render(request, "core/home.html")


def about(request):
    return render(request, "core/about.html")


@login_required
def dashboard(request):
    return render(request, "core/dashboard.html")
