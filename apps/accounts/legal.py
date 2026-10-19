"""Accepting changed Terms / Privacy (site roadmap R16).

``LegalAcceptanceMiddleware`` sends a signed-in person whose recorded versions differ from
``settings.TERMS_VERSION`` / ``PRIVACY_VERSION`` to ``accept_legal`` before anything else — only for
page loads (GET), never mid-form, and never on the pages they need to read or leave: the legal pages,
log-out, the admin, health and app files, JSON and feeds.
"""
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

EXEMPT_PREFIXES = ("/accounts/legal/", "/accounts/logout/", "/terms/", "/privacy/", "/safety/", "/admin/",
                   "/healthz/", "/sw.js", "/manifest.webmanifest", "/static/", "/media/", "/__reload__/",
                   "/notifications/unread.json", "/notifications/unsubscribe/", "/trips/calendar/", "/public/",
                   "/help/", "/contact/", "/account/data/")


def must_accept(request):
    if not getattr(settings, "LEGAL_ACCEPTANCE_REQUIRED", True) or request.method != "GET":
        return False
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not user.needs_legal_acceptance:
        return False
    path = request.path
    if path.startswith(EXEMPT_PREFIXES) or path.endswith(".json") or path.endswith(".ics"):
        return False
    return "application/json" not in request.headers.get("Accept", "")


@login_required
def accept_legal(request):
    target = request.POST.get("next") or request.GET.get("next") or ""
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        target = reverse("pages:dashboard")
    if request.method == "POST":
        request.user.accept_legal()
        return redirect(target)
    if not request.user.needs_legal_acceptance:
        return redirect(target)
    first = not request.user.terms_version
    return render(request, "accounts/accept_legal.html", {"next": target, "first": first,
                                                          "terms_version": settings.TERMS_VERSION,
                                                          "privacy_version": settings.PRIVACY_VERSION})
