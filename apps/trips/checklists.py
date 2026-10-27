"""Checklists on a trip (site roadmap R9): starter templates, ticking, and the views.

Templates are markdown files in ``checklist_templates/`` (named so they can't be mistaken for this
module): a header of ``title`` / ``kind`` / ``summary`` lines, a blank line, then ``- item`` lines;
``- [each] Passport`` makes an item every traveller ticks. ``parse`` is strict (the test suite
parses every file); ``templates()`` skips a bad one.

Ticking (``trips:checklist_tick``) needs ``comment``: a plain form POST that redirects back to the
trip page, or a 204 when Alpine sends it in the background. Creating and editing lists is on Edit
trip (``checklist_new`` / ``_edit`` / ``_delete`` / ``_from_template``, editors).
"""
import logging
from datetime import timedelta
from pathlib import Path

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Checklist, ChecklistItem, ChecklistTick

log = logging.getLogger(__name__)
TEMPLATE_DIR = Path(__file__).resolve().parent / "checklist_templates"
ATTENTION_DAYS = 14
EACH = "[each]"


class TemplateError(ValueError):
    pass


def parse(path):
    """{"slug", "title", "kind", "summary", "items": [(text, per_person)]} or ``TemplateError``."""
    path = Path(path)
    header, _, body = path.read_text(encoding="utf-8").replace("\r\n", "\n").partition("\n\n")
    meta = {}
    for line in header.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            raise TemplateError(f"{path.name}: header line {line!r} is not 'key: value'")
        meta[key.strip()] = value.strip()
    if set(meta) != {"title", "kind", "summary"}:
        raise TemplateError(f"{path.name}: the header needs exactly title, kind and summary")
    if meta["kind"] not in Checklist.Kind.values:
        raise TemplateError(f"{path.name}: kind must be one of {', '.join(Checklist.Kind.values)}")
    items = []
    for line in body.splitlines():
        if not line.strip():
            continue
        if not line.startswith("- "):
            raise TemplateError(f"{path.name}: {line!r} is not a '- item' line")
        text = line[2:].strip()
        per_person = text.startswith(EACH)
        text = text.removeprefix(EACH).strip()
        if not text:
            raise TemplateError(f"{path.name}: an empty item")
        items.append((text, per_person))
    if not items:
        raise TemplateError(f"{path.name}: no items")
    return {"slug": path.stem, **meta, "items": items}


def templates():
    found = []
    for path in sorted(TEMPLATE_DIR.glob("*.md")):
        try:
            found.append(parse(path))
        except TemplateError as exc:
            log.error("Checklist template skipped: %s", exc)
    return found


def start_from(trip, slug):
    template = next((t for t in templates() if t["slug"] == slug), None)
    if template is None:
        raise Http404
    checklist = Checklist.objects.create(trip=trip, title=template["title"], kind=template["kind"],
                                         order=trip.checklists.count())
    ChecklistItem.objects.bulk_create(ChecklistItem(checklist=checklist, text=text, per_person=each, order=n)
                                      for n, (text, each) in enumerate(template["items"]))
    return checklist


# ---------------------------------------------------------------- reading (no queries)

def attach(trip):
    """From the trip page's prefetch (``checklists__items__ticks`` and ``travelers``): each item's
    ``boxes`` [(traveler or None, ticked)] and ``is_done``, each list's ``done`` / ``total``."""
    travelers = list(trip.travelers.all())
    lists = list(trip.checklists.all())
    for checklist in lists:
        checklist.done = checklist.total = 0
        for item in checklist.items.all():
            if item.per_person and travelers:
                ticked = {tick.traveler_id for tick in item.ticks.all()}
                item.boxes = [(traveler, traveler.pk in ticked) for traveler in travelers]
            else:
                item.boxes = [(None, item.done_at is not None)]
            item.missing = sum(1 for _, ticked in item.boxes if not ticked)
            item.is_done = item.missing == 0
            checklist.total += 1
            checklist.done += item.is_done
    return lists


def attention(trip, lists, today=None):
    """How many document ticks are still missing, from ``ATTENTION_DAYS`` before the trip until
    its end (Overview → Needs attention); 0 outside that window."""
    today = today or timezone.localdate()
    if not trip.start_date or not (trip.start_date - timedelta(days=ATTENTION_DAYS) <= today
                                   <= (trip.end_date or trip.start_date)):
        return 0
    return sum(item.missing for checklist in lists if checklist.kind == Checklist.Kind.DOCUMENTS
               for item in checklist.items.all())


# -------------------------------------------------------------------------- views

def _trip(request, pk, action):
    from .views import _readable_trip
    return _readable_trip(request, pk, action)


@login_required
@require_POST
def checklist_tick(request, pk, item_pk):
    trip = _trip(request, pk, "comment")
    item = get_object_or_404(ChecklistItem.objects.select_related("checklist"), pk=item_pk, checklist__trip=trip)
    done = request.POST.get("done") == "1"
    if item.per_person and trip.travelers.exists():
        traveler = get_object_or_404(trip.travelers.all(), pk=request.POST.get("traveler") or 0)
        if done:
            ChecklistTick.objects.get_or_create(item=item, traveler=traveler, defaults={"ticked_by": request.user})
        else:
            ChecklistTick.objects.filter(item=item, traveler=traveler).delete()
    else:
        item.done_at, item.done_by = (timezone.now(), request.user) if done else (None, None)
        item.save(update_fields=["done_at", "done_by"])
    if request.headers.get("X-Requested-With") == "fetch":
        return HttpResponse(status=204)
    return redirect(reverse("trips:trip_detail", args=[trip.pk]) + f"#checklist-{item.checklist_id}")


class ChecklistForm(forms.ModelForm):
    class Meta:
        model = Checklist
        fields = ["title", "kind"]


ItemFormSet = forms.inlineformset_factory(Checklist, ChecklistItem, fields=["text", "per_person", "order"],
                                          extra=5, can_delete=True)


def _edit_back(trip):
    return reverse("trips:trip_settings", args=[trip.pk]) + "#checklists"


@login_required
def checklist_edit(request, pk, checklist_pk=None):
    trip = _trip(request, pk, "edit")
    checklist = get_object_or_404(trip.checklists.all(), pk=checklist_pk) if checklist_pk else Checklist(trip=trip)
    form = ChecklistForm(request.POST or None, instance=checklist)
    formset = ItemFormSet(request.POST or None, instance=checklist, prefix="items")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        if checklist.pk is None:
            checklist.order = trip.checklists.count()
        saved = form.save()
        formset.instance = saved
        formset.save()
        messages.success(request, f"Saved “{saved.title}”.")
        return redirect(_edit_back(trip))
    return render(request, "trips/checklist_form.html",
                  {"trip": trip, "checklist": checklist if checklist.pk else None, "form": form, "formset": formset})


@login_required
@require_POST
def checklist_delete(request, pk, checklist_pk):
    trip = _trip(request, pk, "edit")
    checklist = get_object_or_404(trip.checklists.all(), pk=checklist_pk)
    title = checklist.title
    checklist.delete()
    messages.success(request, f"Deleted “{title}”.")
    return redirect(_edit_back(trip))


@login_required
@require_POST
def checklist_from_template(request, pk):
    trip = _trip(request, pk, "edit")
    checklist = start_from(trip, request.POST.get("template", ""))
    messages.success(request, f"Added “{checklist.title}” with {checklist.items.count()} items. Change it as you like.")
    return redirect(reverse("trips:checklist_edit", args=[trip.pk, checklist.pk]))
