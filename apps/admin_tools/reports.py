"""Members report catalogue items (site roadmap R15), into ``ReportedContent``.

``reports:report`` (``/report/<kind>/<pk>/``, signed in): a reason and a note; one open report per
person per item. Staff are notified (``content_reported``) and see open reports on the staff
dashboard. Three open reports on a *member-submitted* activity or event send it back to the
approval queue (pending, so hidden) until staff decide; places are mostly imported, so reports on
them only notify. Catalogue templates link here with ``partials/_report_link.html`` (by URL name).
"""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.activities.models import Activity
from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event
from apps.locations.models import POI
from apps.notifications.services import notify_staff

from .models import ReportedContent

KINDS = {"activity": Activity, "event": Event, "place": POI}
DETAIL = {"activity": "activities:activity_detail", "event": "events:event_detail", "place": "locations:poi_detail"}
HIDE_AT = 3
REASONS = [("false_info", "Wrong or out-of-date information"), ("spam", "Spam or advertising"),
           ("harassment", "Offensive or abusive"), ("scam", "A scam"), ("other", "Something else")]


class ReportForm(forms.Form):
    reason = forms.ChoiceField(choices=REASONS, widget=forms.RadioSelect)
    description = forms.CharField(label="What's wrong? (optional)", required=False, max_length=1000,
                                  widget=forms.Textarea(attrs={"rows": 3, "class": "sbl-input"}))


def _open_reports(obj):
    return ReportedContent.objects.filter(content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk,
                                          status__in=("pending", "investigating"))


def _member_submitted(obj):
    author = getattr(obj, "submitted_by", None) or getattr(obj, "created_by", None)
    return author is not None and not getattr(author, "can_access_staff", False)


@login_required
def report(request, kind, pk):
    model = KINDS.get(kind)
    if model is None:
        raise Http404
    obj = get_object_or_404(model, pk=pk)
    back = reverse(DETAIL[kind], args=[obj.slug])
    if _open_reports(obj).filter(reporter=request.user).exists():
        messages.info(request, "You've already reported this; staff will look at it.")
        return redirect(back)
    form = ReportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ReportedContent.objects.create(reporter=request.user, content_object=obj,
                                       reason=form.cleaned_data["reason"],
                                       description=form.cleaned_data["description"])
        count = _open_reports(obj).count()
        hidden = False
        if (count >= HIDE_AT and model in (Activity, Event) and _member_submitted(obj)
                and obj.approval_status == ApprovalStatus.APPROVED):
            model.objects.filter(pk=obj.pk).update(approval_status=ApprovalStatus.PENDING)
            hidden = True
        notify_staff("content_reported", f"Reported: {obj}",
                     f"{request.user.username} reported the {kind} “{obj}”: "
                     f"{dict(REASONS)[form.cleaned_data['reason']]}. {count} open report(s)"
                     f"{' — it is hidden until reviewed' if hidden else ''}.", url=back, obj=obj)
        messages.success(request, "Thanks — staff will take a look.")
        return redirect(back)
    return render(request, "admin_tools/report.html", {"form": form, "obj": obj, "kind": kind, "back": back})
