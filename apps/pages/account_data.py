"""A member's own data: download it, or delete the account (site roadmap R13).

Lives in ``pages`` (the site layer) because both reach into every app; ``accounts`` stays below.

**Download** (``export_zip``): a zip of JSON files — account, settings and profiles, the travel
profile and loyalty programs, the bucket list, reviews, notes on trips, notifications, catalogue
contributions, and the trips they're on as they can see them — plus ``files/`` with what they
uploaded. Never another person's private profile (fellow travellers appear by name only).

**Delete** (``schedule`` → ``cancel`` / ``purge``): asking sets ``User.deletion_requested_at``;
signing in again cancels it; ``manage.py purge_deleted_accounts`` (daily) deletes accounts asked
for more than ``GRACE_DAYS`` ago. Purging:

* hands each shared trip they created to the longest-standing other editor (or, with none, the
  longest-standing person on it, made an editor); a trip nobody else is on is deleted with its
  photos and files;
* wipes the private details on their ``Traveler`` and unlinks it; deletes it if no trip uses it;
* deletes their personal photos *with their files*; pictures used on catalogue pages stay;
* deletes their role-request document from private storage;
* then deletes the account: reviews, notes on trips and catalogue items they added stay, with no
  author ("A former member"); everything else of theirs goes with it.
"""
import io
import json
import logging
import os
import zipfile
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.mail import EmailMessage
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import AccountSettings, Profile, RoleRequest, TravelPreferences, UserRole
from apps.activities.models import Activity
from apps.bucketlists.models import BucketListCategory, BucketListItem, BucketListItemCategory, BucketListMilestone
from apps.events.models import Event
from apps.locations.models import POI, City, Country, Region
from apps.media_app.models import Media, MediaAlbum
from apps.notifications.models import Notification
from apps.reviews.models import Review
from apps.trips.models import (
    BookingTask, Checklist, ChecklistItem, Comment, Confirmation, ConfirmationFile, Day, Lodging, Meal, RewardsMembership,
    Section, TransportLeg, Traveler, Trip, TripActivity, TripGrant, TripIdea,
)

log = logging.getLogger(__name__)
GRACE_DAYS = 30
CATALOGUE_PICTURE_MODELS = (Activity, Event, Country, Region, City, POI)
TRAVELER_PRIVATE = ("home_airport", "dietary_notes", "mobility_notes", "passport_country", "seat_preference",
                    "cabin_preference", "bed_preference", "meal_preference", "known_traveler_number",
                    "redress_number", "passport_number", "passport_expires")
USER_FIELDS = ("username", "email", "first_name", "last_name", "date_joined", "last_login", "is_verified",
               "profile_visibility")


# ------------------------------------------------------------------------------- download

def _rows(queryset, exclude=()):
    """Plain dicts for a queryset (Django's serializer), minus ``exclude`` fields."""
    rows = []
    for row in serializers.serialize("python", queryset):
        fields = {k: v for k, v in row["fields"].items() if k not in exclude}
        rows.append({"id": row["pk"], **fields})
    return rows


def _trip_rows(trip):
    """A trip as its member can see it, without anyone's private travel profile."""
    days = Day.objects.filter(trip=trip)
    return {
        "trip": _rows(Trip.objects.filter(pk=trip.pk), exclude=("travelers", "public_token")),
        "travellers": [t.name for t in trip.travelers.all()],
        "days": _rows(days, exclude=("travelers",)),
        "sections": _rows(Section.objects.filter(day__trip=trip)),
        "meals": _rows(Meal.objects.filter(day__trip=trip)),
        "activities": _rows(TripActivity.objects.filter(trip=trip), exclude=("travelers",)),
        "journeys": _rows(TransportLeg.objects.filter(trip=trip)),
        "stays": _rows(Lodging.objects.filter(trip=trip)),
        "confirmations": _rows(Confirmation.objects.filter(trip=trip), exclude=("travelers",)),
        "checklists": _rows(Checklist.objects.filter(trip=trip)),
        "checklist_items": _rows(ChecklistItem.objects.filter(checklist__trip=trip), exclude=("done_by",)),
        "ideas": _rows(TripIdea.objects.filter(trip=trip), exclude=("added_by",)),
        "todos": _todo_rows(trip),
    }


def _todo_rows(trip):
    """The trip's to-dos, each with what it covers by label (booking-todos K1: a to-do may cover several)."""
    from apps.trips.booking_tasks import label
    return [{"id": task.pk, "title": task.title, "priority": task.get_priority_display(), "due": task.due,
             "due_note": task.due_note, "done": task.done, "notes": task.visible_notes,
             "covers": [label(item) for item in task.covered()]}
            for task in BookingTask.objects.filter(trip=trip)]


def export_data(user):
    """{file name: data} — everything of ``user``'s, as JSON-able structures."""
    traveler = Traveler.objects.filter(user=user).first()
    grants = TripGrant.objects.filter(user=user).select_related("trip")
    return {
        "account.json": {
            "user": {f: getattr(user, f) for f in USER_FIELDS},
            "profile": _rows(Profile.objects.filter(user=user)),
            "settings": _rows(AccountSettings.objects.filter(user=user)),
            "travel_preferences": _rows(TravelPreferences.objects.filter(user=user)),
            "roles": _rows(UserRole.objects.filter(user=user), exclude=("granted_by",)),
            "role_requests": _rows(RoleRequest.objects.filter(user=user), exclude=("reviewed_by",)),
        },
        "travel_profile.json": {
            "traveller": _rows(Traveler.objects.filter(pk=getattr(traveler, "pk", None)), exclude=("user",)),
            "loyalty_programs": _rows(RewardsMembership.objects.filter(traveler=traveler)) if traveler else [],
        },
        "bucket_list.json": {
            "goals": _rows(BucketListItem.objects.filter(user=user)),
            "categories": _rows(BucketListCategory.objects.filter(user=user)),
            "goal_categories": _rows(BucketListItemCategory.objects.filter(item__user=user)),
            "badges": _rows(BucketListMilestone.objects.filter(user=user)),
        },
        "reviews.json": _rows(Review.objects.filter(user=user)),
        "trip_notes.json": _rows(Comment.objects.filter(author=user)),
        "notifications.json": _rows(Notification.objects.filter(user=user)),
        "contributions.json": {
            "activities": _rows(Activity.objects.filter(Q(created_by=user) | Q(submitted_by=user))),
            "events": _rows(Event.objects.filter(Q(created_by=user) | Q(submitted_by=user))),
            "places": _rows(POI.objects.filter(submitted_by=user)),
            "cities": _rows(City.objects.filter(submitted_by=user)),
        },
        "trips.json": [{"role": grant.role, **_trip_rows(grant.trip)} for grant in grants
                       if grant.trip.deleted_at is None],
    }


def _files(user):
    """(path in the zip, open file) for everything they uploaded."""
    for media in Media.objects.filter(uploaded_by=user).exclude(file=""):
        yield f"files/photos/{media.pk}-{os.path.basename(media.file.name)}", media.file
    for record in ConfirmationFile.objects.filter(uploaded_by=user):
        yield f"files/tickets/{record.pk}-{record.original_name}", record.file
    for request in RoleRequest.objects.filter(user=user).exclude(supporting_documents=""):
        yield f"files/role_request/{os.path.basename(request.supporting_documents.name)}", request.supporting_documents


def export_zip(user):
    """The download, as bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", (
            f"Your data from {settings.SITE_NAME}, {timezone.now():%Y-%m-%d %H:%M %Z}.\n"
            "Each .json file is one part of your account; files/ holds what you uploaded.\n"
            "Trips are as you can see them; other people appear by name only.\n"))
        for name, data in export_data(user).items():
            archive.writestr(name, json.dumps(data, cls=DjangoJSONEncoder, indent=1, ensure_ascii=False))
        for path, field in _files(user):
            try:
                with field.open("rb") as handle:
                    archive.writestr(path, handle.read())
            except (FileNotFoundError, OSError):
                archive.writestr(path + ".missing.txt", "This file was no longer on the server.")
    return buffer.getvalue()


# ------------------------------------------------------------------------------- delete

def deletion_date(user):
    return user.deletion_requested_at + timedelta(days=GRACE_DAYS) if user.deletion_requested_at else None


def schedule(user):
    """Ask for deletion: hidden now, deleted after ``GRACE_DAYS`` unless they sign in again."""
    user.deletion_requested_at = timezone.now()
    user.save(update_fields=["deletion_requested_at"])
    when = deletion_date(user)
    if user.email and not user.email.endswith("@noemail.invalid"):
        try:
            EmailMessage(
                subject=f"[{settings.SITE_NAME}] Your account will be deleted on {when:%B} {when.day}",
                body=(f"You asked us to delete your {settings.SITE_NAME} account ({user.username}).\n\n"
                      f"It will be deleted on {when:%B} {when.day}, {when.year}. Until then it is hidden and we "
                      "send you no other emails.\n\nChanged your mind? Just sign in before then and the "
                      f"deletion is cancelled.\n\n— {settings.SITE_NAME}\n"),
                from_email=settings.DEFAULT_FROM_EMAIL, to=[user.email]).send()
        except Exception:  # noqa: BLE001 - the request stands even if the email fails
            log.exception("Could not email deletion notice to user %s", user.pk)
    return when


def cancel(user):
    if user.deletion_requested_at:
        user.deletion_requested_at = None
        user.save(update_fields=["deletion_requested_at"])
        return True
    return False


def _delete_media(queryset):
    for media in queryset:
        for field in (media.file, getattr(media, "thumbnail", None)):
            if field:
                field.delete(save=False)
        media.delete()


def _catalogue_picture_ids():
    ids = set()
    for model in CATALOGUE_PICTURE_MODELS:
        ids.update(model.objects.exclude(featured_media=None).values_list("featured_media_id", flat=True))
    return ids


def _hand_over_or_delete_trips(user):
    from django.contrib.contenttypes.models import ContentType
    handed, deleted = 0, 0
    trip_type = ContentType.objects.get_for_model(Trip)
    for trip in Trip.objects.filter(created_by=user):
        others = list(trip.grants.exclude(user=user).filter(user__is_active=True).select_related("user")
                      .order_by("granted_at", "pk"))
        if others:
            heir = next((g for g in others if g.role == "editor"), others[0])
            if heir.role != "editor":
                heir.role = "editor"
                heir.save(update_fields=["role"])
            Trip.objects.filter(pk=trip.pk).update(created_by=heir.user)
            handed += 1
        else:
            _delete_media(Media.objects.filter(content_type=trip_type, object_id=trip.pk))
            trip.delete()  # ticket files go with their confirmations (trips.signals)
            deleted += 1
    return handed, deleted


def _scrub_traveler(user):
    traveler = Traveler.objects.filter(user=user).first()
    if traveler is None:
        return
    RewardsMembership.objects.filter(traveler=traveler).delete()
    for name in TRAVELER_PRIVATE:
        field = Traveler._meta.get_field(name)
        setattr(traveler, name, None if field.null else "")
    traveler.user = None
    traveler.save()
    used = (traveler.trips.exists() or traveler.days.exists() or traveler.expenses_paid.exists()
            or traveler.confirmations.exists() or traveler.trip_activities.exists())
    if not used:
        traveler.delete()


@transaction.atomic
def purge(user):
    """Delete ``user`` for good (see the module docstring). Returns a one-line summary."""
    handed, deleted = _hand_over_or_delete_trips(user)
    keep = _catalogue_picture_ids()
    _delete_media(Media.objects.filter(uploaded_by=user).exclude(pk__in=keep))
    MediaAlbum.objects.filter(user=user).delete()
    for request in RoleRequest.objects.filter(user=user).exclude(supporting_documents=""):
        request.supporting_documents.delete(save=False)
    _scrub_traveler(user)
    username = user.username
    user.delete()
    return f"{username}: {handed} trip(s) handed over, {deleted} deleted"


def due_for_purge(now=None):
    cutoff = (now or timezone.now()) - timedelta(days=GRACE_DAYS)
    return get_user_model().objects.filter(deletion_requested_at__lte=cutoff)
