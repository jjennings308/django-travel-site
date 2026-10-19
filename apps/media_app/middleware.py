"""Turns a refused upload (``quota.QuotaExceeded``, site roadmap R15) into a message and a trip back
to the page, so no view needs its own handling."""
from django.contrib import messages
from django.shortcuts import redirect

from .quota import QuotaExceeded


class QuotaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, QuotaExceeded):
            messages.error(request, str(exception))
            return redirect(request.get_full_path())
        return None
