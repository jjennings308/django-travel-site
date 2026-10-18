"""Tickets and documents on confirmations (site roadmap R5): checking uploads, and the views.

An upload is accepted by its *contents*, not its name: a PDF (starts ``%PDF-``), or an image
Pillow reads as PNG, JPEG or HEIC/HEIF (HEIC is stored as JPEG, as everywhere on the site, since
only Safari shows it). At most ``MAX_FILE_MB`` each and ``MAX_TRIP_MB`` for all of a trip's files.

``trips:confirmation_file_add`` / ``confirmation_file_delete`` are for editors;
``trips:confirmation_file`` (the download) for anyone who can see the trip. Files are served inline
under their original name, with nosniff, no caching and a sandbox CSP.
"""
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db.models import Sum
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from PIL import Image, UnidentifiedImageError

from apps.core.utils.images import heic_to_jpeg

from .models import ConfirmationFile

MAX_FILE_MB = 10
MAX_TRIP_MB = 200
MB = 1024 * 1024
IMAGE_TYPES = {"PNG": ("image/png", ".png"), "JPEG": ("image/jpeg", ".jpg")}
HEIF_FORMATS = {"HEIF", "HEIC", "AVIF"}


class Refused(ValueError):
    """Why a file can't be added (shown to the editor)."""


def inspect(upload):
    """(content to store, content type, file name) for an acceptable upload, else ``Refused``."""
    name = os.path.basename(upload.name or "file")[:150]
    stem = os.path.splitext(name)[0] or "file"
    upload.seek(0)
    head = upload.read(5)
    upload.seek(0)
    if head == b"%PDF-":
        return upload, "application/pdf", f"{stem}.pdf"
    try:
        with Image.open(upload) as image:
            fmt = image.format
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise Refused(f"{name}: only PDF, PNG, JPEG or iPhone (HEIC) photos can be added.")
    upload.seek(0)
    if fmt in HEIF_FORMATS:
        return ContentFile(heic_to_jpeg(upload), name=f"{stem}.jpg"), "image/jpeg", f"{stem}.jpg"
    if fmt not in IMAGE_TYPES:
        raise Refused(f"{name}: only PDF, PNG, JPEG or iPhone (HEIC) photos can be added.")
    content_type, ext = IMAGE_TYPES[fmt]
    return upload, content_type, f"{stem}{ext}"


def trip_total(trip):
    return ConfirmationFile.objects.filter(confirmation__trip=trip).aggregate(total=Sum("size"))["total"] or 0


def add(confirmation, upload, user):
    """Store one upload on ``confirmation``; ``Refused`` says why not."""
    if upload.size > MAX_FILE_MB * MB:
        raise Refused(f"{upload.name}: over {MAX_FILE_MB} MB.")
    content, content_type, name = inspect(upload)
    size = content.size
    if trip_total(confirmation.trip) + size > MAX_TRIP_MB * MB:
        raise Refused(f"{upload.name}: this trip's files would go over {MAX_TRIP_MB} MB. Remove some first.")
    record = ConfirmationFile(confirmation=confirmation, original_name=name, content_type=content_type, size=size,
                              uploaded_by=user)
    record.file.save(name, content, save=False)
    record.save()
    return record


def _back(request, trip, confirmation):
    from .views import _back as back
    return back(request, reverse("trips:confirmation_edit", args=[trip.pk, confirmation.pk]) + "#files")


@login_required
@require_POST
def confirmation_file_add(request, pk, confirmation_pk):
    from .views import _readable_trip
    trip = _readable_trip(request, pk, "edit")
    confirmation = get_object_or_404(trip.confirmations.all(), pk=confirmation_pk)
    uploads = request.FILES.getlist("files")
    if not uploads:
        messages.error(request, "Choose a file to add.")
    added = []
    for upload in uploads:
        try:
            added.append(add(confirmation, upload, request.user).original_name)
        except Refused as reason:
            messages.error(request, str(reason))
    if added:
        messages.success(request, f"Added {', '.join(added)} to {confirmation.confirmation_number}.")
    return redirect(_back(request, trip, confirmation))


@login_required
@require_POST
def confirmation_file_delete(request, pk, file_pk):
    from .views import _readable_trip
    trip = _readable_trip(request, pk, "edit")
    record = get_object_or_404(ConfirmationFile.objects.select_related("confirmation"), pk=file_pk,
                               confirmation__trip=trip)
    name, confirmation = record.original_name, record.confirmation
    record.delete()
    messages.success(request, f"Removed {name} from {confirmation.confirmation_number}.")
    return redirect(_back(request, trip, confirmation))


@login_required
def confirmation_file(request, pk, file_pk):
    from .views import _readable_trip
    trip = _readable_trip(request, pk, "view")
    record = get_object_or_404(ConfirmationFile, pk=file_pk, confirmation__trip=trip)
    response = FileResponse(record.file.open("rb"), as_attachment=False, filename=record.original_name,
                            content_type=record.content_type)
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    response["Content-Security-Policy"] = "sandbox"
    return response
