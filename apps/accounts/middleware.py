"""accounts middleware: accepting changed Terms / Privacy first (site roadmap R16; see legal.py)."""
from urllib.parse import urlencode

from django.shortcuts import redirect
from django.urls import reverse


class LegalAcceptanceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from .legal import must_accept
        if must_accept(request):
            return redirect(f"{reverse('accept_legal')}?{urlencode({'next': request.get_full_path()})}")
        return self.get_response(request)
