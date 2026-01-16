from django.contrib.auth.decorators import login_required
from django.shortcuts import render

@login_required
def events_dashboard(request):
    """
    Dashboard landing page for the X app
    """
    context = {
        "app_name": "Events",
        "page_title": "Events Dashboard",
    }
    return render(request, "events/dashboard.html", context)
