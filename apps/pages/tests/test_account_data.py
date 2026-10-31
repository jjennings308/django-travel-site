"""Download your data, and delete your account (site roadmap R13)."""
import io
import json
import os
import shutil
import tempfile
import zipfile
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.activities.models import Activity, ActivityCategory
from apps.bucketlists.models import BucketListItem
from apps.media_app.models import Media
from apps.pages import account_data
from apps.reviews.models import Review
from apps.trips import files
from apps.trips.models import (
    Comment, Confirmation, ConfirmationFile, Lodging, RewardsMembership, Traveler, Trip, TripGrant, TripRole,
)

User = get_user_model()
PDF = b"%PDF-1.4\n%%EOF\n"


class Fixture(TestCase):
    def setUp(self):
        self.media_root, self.private_root = tempfile.mkdtemp(), tempfile.mkdtemp()
        for folder in (self.media_root, self.private_root):
            self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media_root, PRIVATE_MEDIA_ROOT=self.private_root)
        override.enable()
        self.addCleanup(override.disable)
        cache.clear()
        self.ada = User.objects.create_user("ada", "ada@example.com", "pw-1234-abcd", first_name="Ada")
        self.bob = User.objects.create_user("bob", "bob@example.com", "pw-1234-abcd", first_name="Bob")
        self.cy = User.objects.create_user("cy", "cy@example.com", "pw-1234-abcd", first_name="Cy")
        self.ada_traveler = Traveler.objects.get(user=self.ada)
        Traveler.objects.filter(pk=self.ada_traveler.pk).update(passport_number="ADA-PASSPORT", home_airport="PIT")
        self.bob_traveler = Traveler.objects.get(user=self.bob)
        Traveler.objects.filter(pk=self.bob_traveler.pk).update(passport_number="BOB-PASSPORT")
        RewardsMembership.objects.create(traveler=self.ada_traveler, program="Delta SkyMiles", member_number="ADA-MILES")
        # A shared trip Ada created; Bob (viewer) and Cy (editor, joined later) are on it.
        self.shared = Trip.objects.create(name="Rome", start_date=date(2027, 5, 1), end_date=date(2027, 5, 4),
                                          created_by=self.ada)
        for user, role in ((self.ada, "editor"), (self.bob, "viewer"), (self.cy, "editor")):
            TripGrant.objects.create(trip=self.shared, user=user, role=role)
        self.shared.travelers.set([self.ada_traveler, self.bob_traveler])
        # A trip only Ada is on.
        self.solo = Trip.objects.create(name="Solo", start_date=date(2027, 6, 1), end_date=date(2027, 6, 2),
                                        created_by=self.ada)
        TripGrant.objects.create(trip=self.solo, user=self.ada, role="editor")
        stay = Lodging.objects.create(trip=self.solo, name="Inn", check_in=date(2027, 6, 1), check_out=date(2027, 6, 2))
        self.solo_ticket = files.add(Confirmation.attach_number(self.solo, "SOLO1", stay),
                                     SimpleUploadedFile("solo.pdf", PDF), self.ada)
        shared_stay = Lodging.objects.create(trip=self.shared, name="Hotel", check_in=date(2027, 5, 1),
                                             check_out=date(2027, 5, 4))
        self.shared_ticket = files.add(Confirmation.attach_number(self.shared, "ROMA1", shared_stay),
                                       SimpleUploadedFile("rome.pdf", PDF), self.ada)
        self.goal = BucketListItem.objects.create(user=self.ada, custom_title="See the Colosseum")
        self.photo = Media.objects.create(file=ContentFile(b"jpegbytes", name="goal.jpg"), uploaded_by=self.ada,
                                          media_type="image", content_object=self.goal)
        category, _ = ActivityCategory.objects.get_or_create(name="Tours", defaults={"slug": "tours"})
        self.activity = Activity.objects.create(name="Vespa tour", category=category, created_by=self.ada,
                                                description="x")
        self.catalogue_picture = Media.objects.create(file=ContentFile(b"jpegbytes", name="vespa.jpg"),
                                                      uploaded_by=self.ada, media_type="image",
                                                      content_object=self.activity)
        Activity.objects.filter(pk=self.activity.pk).update(featured_media=self.catalogue_picture)
        self.review = Review.objects.create(user=self.ada, activity=self.activity, rating=5, comment="Great")
        self.note = Comment.objects.create(author=self.ada, content_object=self.shared, body="Bring sun cream")
        mail.outbox = []


class ExportTests(Fixture):
    def zip(self):
        self.client.force_login(self.ada)
        response = self.client.post(reverse("pages:data_export"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        return zipfile.ZipFile(io.BytesIO(response.content))

    def test_contains_their_data_and_files(self):
        archive = self.zip()
        names = archive.namelist()
        for part in ("README.txt", "account.json", "travel_profile.json", "bucket_list.json", "reviews.json",
                     "trip_notes.json", "trips.json", "contributions.json"):
            self.assertIn(part, names)
        self.assertTrue(any(n.startswith(f"files/photos/{self.photo.pk}-") for n in names))  # stored names
        self.assertTrue(any(n.startswith("files/tickets/") and n.endswith("rome.pdf") for n in names))
        profile = json.loads(archive.read("travel_profile.json"))
        self.assertEqual(profile["traveller"][0]["passport_number"], "ADA-PASSPORT")
        self.assertEqual(profile["loyalty_programs"][0]["member_number"], "ADA-MILES")
        self.assertIn("See the Colosseum", archive.read("bucket_list.json").decode())

    def test_never_anyone_elses_private_details(self):
        archive = self.zip()
        everything = b"".join(archive.read(n) for n in archive.namelist())
        self.assertNotIn(b"BOB-PASSPORT", everything)
        self.assertNotIn(b"bob@example.com", everything)
        trips = json.loads(archive.read("trips.json"))
        rome = next(t for t in trips if t["trip"][0]["name"] == "Rome")
        self.assertIn("Bob", " ".join(rome["travellers"]) + " bob")  # by name only

    def test_todos_list_what_they_cover(self):
        """Booking-todos K1: a to-do's covered items by label."""
        from apps.trips.models import BookingTask, TransportLeg
        out = TransportLeg.objects.create(trip=self.shared, origin="Roma Termini", destination="Firenze SMN",
                                          date=date(2027, 5, 2))
        back = TransportLeg.objects.create(trip=self.shared, origin="Firenze SMN", destination="Roma Termini",
                                           date=date(2027, 5, 3))
        task = BookingTask.objects.create(trip=self.shared, title="Train tickets")
        task.link(out)
        task.link(back)
        rome = next(t for t in json.loads(self.zip().read("trips.json")) if t["trip"][0]["name"] == "Rome")
        self.assertEqual(rome["todos"][0]["covers"], ["Roma Termini → Firenze SMN", "Firenze SMN → Roma Termini"])

    def test_costs_list_what_they_paid_for(self):
        """Budget-estimates B3: each recorded cost, people by name, and what it was for."""
        from decimal import Decimal
        from apps.trips.models import Confirmation, Traveler, TripExpense
        payer = Traveler.objects.create(name="Payer P")
        booking = Confirmation.objects.create(trip=self.shared, confirmation_number="GCH7JS", cost=Decimal("40"),
                                              currency="EUR")
        expense = TripExpense(trip=self.shared, description="Train", amount=Decimal("40"), currency="EUR",
                              paid_by=payer, category="transport")
        expense.set_for(booking)
        expense.save()
        rome = next(t for t in json.loads(self.zip().read("trips.json")) if t["trip"][0]["name"] == "Rome")
        cost = rome["costs"][0]
        self.assertEqual((cost["for"], cost["paid_by"], cost["shared_with"]), ("GCH7JS", "Payer P", ["everyone"]))

    def test_rate_limited(self):
        self.client.force_login(self.ada)
        self.client.post(reverse("pages:data_export"))
        again = self.client.post(reverse("pages:data_export"))
        self.assertEqual(again.status_code, 302)

    def test_signed_in_only_and_settings_link(self):
        self.assertEqual(self.client.post(reverse("pages:data_export")).status_code, 302)
        self.client.force_login(self.ada)
        self.assertContains(self.client.get(reverse("settings")), reverse("pages:my_data"))


class ScheduleTests(Fixture):
    def ask(self, password="pw-1234-abcd", confirm=True):
        self.client.force_login(self.ada)
        data = {"password": password}
        if confirm:
            data["confirm"] = "on"
        return self.client.post(reverse("pages:my_data"), data)

    def test_needs_password_and_confirmation(self):
        self.assertEqual(self.ask(password="wrong").status_code, 200)
        self.assertEqual(self.ask(confirm=False).status_code, 200)
        self.ada.refresh_from_db()
        self.assertIsNone(self.ada.deletion_requested_at)

    def test_scheduled_signed_out_emailed_and_hidden(self):
        response = self.ask()
        self.assertRedirects(response, reverse("pages:home"), fetch_redirect_response=False)
        self.ada.refresh_from_db()
        self.assertIsNotNone(self.ada.deletion_requested_at)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(mail.outbox[-1].to, ["ada@example.com"])
        self.assertIn("will be deleted on", mail.outbox[-1].subject)
        # Hidden: the public bucket list 404s even if the profile was public; no notification emails.
        User.objects.filter(pk=self.ada.pk).update(profile_visibility="public")
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(reverse("bucketlists:public_list", args=["ada"])).status_code, 404)
        from apps.notifications.services import wants_email
        self.ada.refresh_from_db()
        self.assertFalse(wants_email(self.ada))

    def test_signing_in_cancels(self):
        self.ask()
        self.client.post(reverse("login"), {"username": "ada@example.com", "password": "pw-1234-abcd"})
        self.ada.refresh_from_db()
        self.assertIsNone(self.ada.deletion_requested_at)

    def test_staff_dashboard_lists_it(self):
        self.ask()
        staff = User.objects.create_superuser("root", "root@example.com", "pw-1234-abcd")
        self.client.force_login(staff)
        self.assertContains(self.client.get(reverse("pages:staff_dashboard")), "Accounts scheduled for deletion")


class PurgeTests(Fixture):
    def purge(self, days_ago=31):
        User.objects.filter(pk=self.ada.pk).update(deletion_requested_at=timezone.now() - timedelta(days=days_ago))
        out = io.StringIO()
        call_command("purge_deleted_accounts", stdout=out)
        return out.getvalue()

    def test_not_before_the_grace_period(self):
        self.assertIn("No accounts", self.purge(days_ago=10))
        self.assertTrue(User.objects.filter(pk=self.ada.pk).exists())

    def test_purge(self):
        photo_path, catalogue_path = self.photo.file.path, self.catalogue_picture.file.path
        solo_ticket_path, shared_ticket_path = self.solo_ticket.file.path, self.shared_ticket.file.path
        output = self.purge()
        self.assertIn("1 trip(s) handed over, 1 deleted", output)
        self.assertFalse(User.objects.filter(username="ada").exists())
        # The shared trip goes to the longest-standing other editor (Cy, not viewer Bob).
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.created_by, self.cy)
        self.assertEqual(TripGrant.objects.filter(trip=self.shared).count(), 2)
        # The solo trip, its ticket and file are gone.
        self.assertFalse(Trip.objects.filter(pk=self.solo.pk).exists())
        self.assertFalse(os.path.exists(solo_ticket_path))
        # The shared trip's ticket stays with the group's booking.
        self.assertTrue(ConfirmationFile.objects.filter(pk=self.shared_ticket.pk, uploaded_by=None).exists())
        self.assertTrue(os.path.exists(shared_ticket_path))
        # Personal photo deleted with its file; the catalogue picture stays.
        self.assertFalse(Media.objects.filter(pk=self.photo.pk).exists())
        self.assertFalse(os.path.exists(photo_path))
        self.assertTrue(Media.objects.filter(pk=self.catalogue_picture.pk, uploaded_by=None).exists())
        self.assertTrue(os.path.exists(catalogue_path))
        # Catalogue activity, review and trip note stay, from "A former member".
        self.assertTrue(Activity.objects.filter(pk=self.activity.pk, created_by=None).exists())
        review = Review.objects.get(pk=self.review.pk)
        self.assertEqual(review.author_name, "A former member")
        self.assertEqual(Comment.objects.get(pk=self.note.pk).author_name, "A former member")
        # Goals gone; the roster entry is kept (Bob's trip names her) but scrubbed and unlinked.
        self.assertFalse(BucketListItem.objects.filter(pk=self.goal.pk).exists())
        traveler = Traveler.objects.get(pk=self.ada_traveler.pk)
        self.assertEqual((traveler.user_id, traveler.passport_number, traveler.home_airport), (None, "", ""))
        self.assertFalse(RewardsMembership.objects.filter(traveler=traveler).exists())
        # The note still shows on the trip page, from "A former member".
        self.client.force_login(self.cy)
        page = self.client.get(reverse("trips:trip_detail", args=[self.shared.pk]))
        self.assertContains(page, "Bring sun cream")
        self.assertContains(page, "A former member")
        # Others untouched.
        self.assertTrue(User.objects.filter(username="bob").exists())
        self.assertEqual(Traveler.objects.get(pk=self.bob_traveler.pk).passport_number, "BOB-PASSPORT")

    def test_with_no_other_editor_the_longest_standing_member_becomes_one(self):
        TripGrant.objects.filter(trip=self.shared, user=self.cy).delete()
        self.purge()
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.created_by, self.bob)
        self.assertEqual(TripGrant.objects.get(trip=self.shared, user=self.bob).role, TripRole.EDITOR)

    def test_an_unused_roster_entry_is_deleted(self):
        self.shared.travelers.remove(self.ada_traveler)
        self.purge()
        self.assertFalse(Traveler.objects.filter(pk=self.ada_traveler.pk).exists())

    def test_dry_run_changes_nothing(self):
        User.objects.filter(pk=self.ada.pk).update(deletion_requested_at=timezone.now() - timedelta(days=40))
        out = io.StringIO()
        call_command("purge_deleted_accounts", "--dry-run", stdout=out)
        self.assertIn("Would delete ada", out.getvalue())
        self.assertTrue(User.objects.filter(pk=self.ada.pk).exists())
