from django.contrib.auth.decorators import login_required
from django.shortcuts import render

@login_required
def dashboard(request):
    """
    Dashboard landing page for the X app
    """
    context = {
        "app_name": "Trips",
        "page_title": "Trips Dashboard",
    }
    return render(request, "trips/dashboard.html", context)
