from django.contrib.auth.decorators import login_required
from django.shortcuts import render

@login_required
def activities_dashboard(request):
    """
    Dashboard landing page for the X app
    """
    context = {
        "app_name": "Activities",
        "page_title": "Activities Dashboard",
    }
    return render(request, "activities/dashboard.html", context)
