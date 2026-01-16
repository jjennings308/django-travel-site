from django.contrib.auth.decorators import login_required
from django.shortcuts import render

@login_required
def bucketlists_dashboard(request):
    """
    Dashboard landing page for the X app
    """
    context = {
        "app_name": "Bucketlists",
        "page_title": "Bucketlists Dashboard",
    }
    return render(request, "bucketlists/dashboard.html", context)
