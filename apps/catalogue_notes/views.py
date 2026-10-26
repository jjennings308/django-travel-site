"""Notes on catalogue pages (docs/plans/catalogue-notes.md, N1): the Good to know card's list (loaded after
the place / activity / event page, so the page itself pays no query), and adding, editing, deleting and
reporting a note."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.approval_system.models import ApprovalStatus

from .forms import CatalogueNoteForm
from .models import CatalogueNote
from .services import KINDS, get_target, kind_of, notes_for, target_url


def _is_staff(user):
    return user.is_authenticated and (user.is_staff or getattr(user, "can_access_staff", False))


def can_edit(user, note):
    """Staff always; the member who wrote it until it's approved."""
    if _is_staff(user):
        return True
    return (user.is_authenticated and note.created_by_id == user.pk
            and note.approval_status != ApprovalStatus.APPROVED)


def for_target(request, kind, slug):
    target = get_target(kind, slug)
    notes = notes_for(target, request.user)
    for note in notes:
        note.editable = can_edit(request.user, note)
    return render(request, "catalogue_notes/_list.html", {"target": target, "kind": kind, "notes": notes,
                                                          "target_url": target_url(target)})


@login_required
def add(request, kind, slug):
    target = get_target(kind, slug)
    form = CatalogueNoteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        note = form.save(commit=False)
        setattr(note, KINDS[kind][1], target)
        note.created_by = request.user
        if _is_staff(request.user):
            note.approval_status = ApprovalStatus.APPROVED
            note.save()
            messages.success(request, "Your note is up.")
        else:
            note.save()
            note.submit_for_review(request.user)
            messages.success(request, "Thanks! Your note was sent for review; only you can see it until it's approved.")
        return redirect(note.get_absolute_url())
    return render(request, "catalogue_notes/note_form.html", {"form": form, "target": target, "kind": kind,
                                                              "note": None, "target_url": target_url(target)})


@login_required
def edit(request, pk):
    note = get_object_or_404(CatalogueNote.objects.select_related("poi", "activity", "event"), pk=pk)
    if not can_edit(request.user, note):
        raise PermissionDenied
    form = CatalogueNoteForm(request.POST or None, instance=note)
    if request.method == "POST" and form.is_valid():
        note = form.save()
        if not _is_staff(request.user) and note.approval_status in (
                ApprovalStatus.REJECTED, ApprovalStatus.CHANGES_REQUESTED, ApprovalStatus.DRAFT):
            note.submit_for_review(request.user)
            messages.success(request, "Saved and sent for review again.")
        else:
            messages.success(request, "Saved.")
        return redirect(note.get_absolute_url())
    return render(request, "catalogue_notes/note_form.html", {"form": form, "target": note.target,
                                                              "kind": kind_of(note.target), "note": note,
                                                              "target_url": target_url(note.target)})


@login_required
def delete(request, pk):
    note = get_object_or_404(CatalogueNote.objects.select_related("poi", "activity", "event"), pk=pk)
    if not can_edit(request.user, note):
        raise PermissionDenied
    back = note.get_absolute_url()
    if request.method == "POST":
        note.delete()
        messages.success(request, "Note deleted.")
        return redirect(back)
    return render(request, "catalogue_notes/note_confirm_delete.html", {"note": note, "back": back})


@login_required
@require_POST
def report(request, pk):
    """Tell staff a published note looks wrong or out of date."""
    from apps.notifications.services import notify_staff
    note = get_object_or_404(CatalogueNote.objects.select_related("poi", "activity", "event"), pk=pk,
                             approval_status=ApprovalStatus.APPROVED)
    reason = (request.POST.get("reason") or "").strip()[:500]
    notify_staff("content_reported", f"A note on “{note.target_name}” was reported",
                 f"{request.user.get_username()}: {reason or 'no reason given'}\n\n“{note.text[:300]}”",
                 note.get_absolute_url(), obj=note)
    messages.success(request, "Thanks, staff will take a look.")
    return redirect(note.get_absolute_url())
