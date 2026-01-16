from django.contrib.auth.decorators import login_required
from django.shortcuts import render

@login_required
def dashboard(request):
    """
    Dashboard landing page for the X app
    """
    context = {
        "app_name": "Locations",
        "page_title": "Locations Dashboard",
    }
    return render(request, "locations/dashboard.html", context)
