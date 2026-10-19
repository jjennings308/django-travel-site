# notifications/views.py
"""The signed-in user's notifications: the list page, opening one, and the
small JSON feed the header bell loads after the page (so pages pay no query)."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
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


@csrf_exempt  # the signed token is the credential; mail apps POST "List-Unsubscribe=One-Click" here
def unsubscribe(request, token):
    """Stop (or, with ``undo``, restart) emails of one kind for one person, signed out (R15)."""
    from django.contrib.auth import get_user_model
    from django.http import Http404, HttpResponse
    from .models import UserNotificationPreference
    from .services import KINDS, notification_type, read_unsubscribe_token
    found = read_unsubscribe_token(token)
    user = get_user_model().objects.filter(pk=found[0]).first() if found else None
    if user is None:
        raise Http404
    kind = found[1]
    label = KINDS.get(kind, kind)
    if request.method == "POST":
        on = request.POST.get("undo") == "1"
        pref, _ = UserNotificationPreference.objects.get_or_create(user=user,
                                                                   notification_type=notification_type(kind))
        pref.email_enabled = on
        pref.save(update_fields=["email_enabled"])
        if request.POST.get("List-Unsubscribe") == "One-Click":
            return HttpResponse("Unsubscribed.", content_type="text/plain")
        return render(request, "notifications/unsubscribed.html",
                      {"label": label, "token": token, "on": on})
    return render(request, "notifications/unsubscribe.html", {"label": label, "token": token})
