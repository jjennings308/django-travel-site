"""Your data: download it, or delete your account (site roadmap R13). Rules in ``account_data``."""
from django import forms
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import account_data

EXPORT_EVERY_SECONDS = 600


class DeleteAccountForm(forms.Form):
    password = forms.CharField(label="Your password", widget=forms.PasswordInput(attrs={"autocomplete": "current-password",
                                                                                        "class": "sbl-input"}))
    confirm = forms.BooleanField(label="I understand my account will be deleted after 30 days unless I sign in again")

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("That isn't your password.")
        return password


@login_required
def my_data(request):
    form = DeleteAccountForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        when = account_data.schedule(request.user)
        logout(request)
        messages.success(request, f"Your account will be deleted on {when:%B} {when.day}, {when.year}. "
                                  "Sign in before then to cancel.")
        return redirect("pages:home")
    return render(request, "pages/my_data.html", {"form": form, "grace_days": account_data.GRACE_DAYS})


@login_required
@require_POST
def data_export(request):
    key = f"data-export:{request.user.pk}"
    if not cache.add(key, 1, EXPORT_EVERY_SECONDS):
        messages.error(request, "You downloaded your data a few minutes ago. Try again in 10 minutes.")
        return redirect("pages:my_data")
    response = HttpResponse(account_data.export_zip(request.user), content_type="application/zip")
    name = f"sharebucketlist-{request.user.username}-{timezone.localdate():%Y-%m-%d}.zip"
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    response["Cache-Control"] = "private, no-store"
    return response
