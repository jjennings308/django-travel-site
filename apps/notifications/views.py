# notifications/views.py
"""The signed-in user's notifications: the list page, opening one, and the
small JSON feed the header bell loads after the page (so pages pay no query)."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Notification


def _mine(request):
    return Notification.objects.filter(user=request.user, is_archived=False)


@login_required
def notification_list(request):
    page = Paginator(_mine(request).order_by("-created_at"), 25).get_page(request.GET.get("page"))
    return render(request, "notifications/list.html", {
        "page_obj": page, "unread": _mine(request).filter(is_read=False).count(),
    })


@login_required
def unread_count(request):
    """{"unread": n, "latest": [{title, url, read, when}]} for the header bell."""
    latest = [
        {"title": n.title, "url": reverse("notifications:open", args=[n.pk]), "read": n.is_read,
         "when": timezone.localtime(n.created_at).strftime("%b %-d")}
        for n in _mine(request).order_by("-created_at")[:5]
    ]
    return JsonResponse({"unread": _mine(request).filter(is_read=False).count(), "latest": latest})


@login_required
def open_notification(request, pk):
    """Mark one as read and go to what it's about."""
    note = get_object_or_404(_mine(request), pk=pk)
    if not note.is_read:
        note.is_read, note.read_at = True, timezone.now()
        note.save(update_fields=["is_read", "read_at"])
    url = note.action_url if note.action_url.startswith("/") else ""
    return redirect(url or "notifications:list")


@login_required
@require_POST
def mark_all_read(request):
    _mine(request).filter(is_read=False).update(is_read=True, read_at=timezone.now())
    return redirect("notifications:list")
