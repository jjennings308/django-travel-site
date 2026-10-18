"""Change records and the change digest (site roadmap R7)."""
import io
import shutil
import tempfile
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.current import acting_as
from apps.notifications.models import Notification
from apps.trips import changes
from apps.trips.models import (
    Confirmation, Day, Lodging, Meal, Section, TransportLeg, Trip, TripActivity, TripChange, TripGrant, TripRole,
)

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ChangeFixture(TestCase):
    def setUp(self):
        self.ed = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd", first_name="Ed")
        self.vi = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd", first_name="Vi")
        self.co = User.objects.create_user("co", "co@example.com", "pw-1234-abcd", first_name="Co")
        self.trip = Trip.objects.create(name="Bavaria", start_date=date(2027, 9, 18), end_date=date(2027, 9, 21),
                                        created_by=self.ed)
        for user, role in ((self.ed, TripRole.EDITOR), (self.vi, TripRole.VIEWER), (self.co, TripRole.COMMENTOR)):
            TripGrant.objects.create(trip=self.trip, user=user, role=role)
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 19))
        self.leg = TransportLeg.objects.create(
            trip=self.trip, mode="train", operator="DB", service_number="ICE 511", origin="Frankfurt Hbf",
            destination="Augsburg Hbf", date=date(2027, 9, 19),
            departure_at=datetime(2027, 9, 19, 8, 0, tzinfo=dt_timezone.utc),
            arrival_at=datetime(2027, 9, 19, 11, 0, tzinfo=dt_timezone.utc),
            origin_timezone="Europe/Berlin", destination_timezone="Europe/Berlin")
        TripChange.objects.all().delete()  # the fixture's own "Added …" lines
        mail.outbox = []

    def summaries(self):
        return list(TripChange.objects.order_by("id").values_list("summary", flat=True))


class CaptureTests(ChangeFixture):
    def test_leg_time_change_reads_in_local_time(self):
        with acting_as(self.ed):
            self.leg.departure_at = datetime(2027, 9, 19, 8, 30, tzinfo=dt_timezone.utc)
            self.leg.save()
        change = TripChange.objects.get()
        self.assertEqual(change.summary,
                         "Changed Frankfurt Hbf → Augsburg Hbf: departs 10:00 AM CEST → 10:30 AM CEST")
        self.assertEqual((change.kind, change.actor, change.item_type, change.item_id),
                         ("changed", self.ed, "transportleg", self.leg.pk))

    def test_saving_without_a_change_records_nothing(self):
        self.leg.save()
        self.day.save()
        self.assertEqual(self.summaries(), [])

    def test_added_and_removed(self):
        stay = Lodging.objects.create(trip=self.trip, name="Hotel Drei Mohren", check_in=date(2027, 9, 19),
                                      check_out=date(2027, 9, 21))
        stay.delete()
        self.assertEqual(self.summaries(), ["Added stay Hotel Drei Mohren", "Removed stay Hotel Drei Mohren"])

    def test_each_kind_of_item(self):
        activity = TripActivity.objects.create(trip=self.trip, day=self.day, title="Brewery tour")
        activity.start_time = time(14, 30)
        activity.save()
        meal = Meal.objects.create(day=self.day, name="Bräustüberl", meal_type="dinner")
        meal.reserved_time = time(19, 0)
        meal.save()
        section = Section.objects.create(day=self.day, section_type="narrative", title="Morning",
                                         content={"paragraphs": ["Walk"]})
        section.content = {"paragraphs": ["Walk", "Coffee"]}
        section.save()
        self.day.theme = "Old town"
        self.day.save()
        confirmation = Confirmation.attach_number(self.trip, "DB-1", self.leg, provider="DB")
        confirmation.unlink(self.leg)
        self.assertEqual(self.summaries(), [
            "Added “Brewery tour”",
            "Changed “Brewery tour”: starts none → 2:30 PM",
            "Added dinner at Bräustüberl",
            "Changed dinner at Bräustüberl: reservation none → 7:00 PM",
            "Added “Morning” on Day 1",
            "Changed “Morning” on Day 1: text changed",
            "Changed Day 1: theme none → Old town",
            "Added confirmation DB-1",
            "Added confirmation DB-1 to Frankfurt Hbf→Augsburg Hbf",
            "Removed confirmation DB-1 from Frankfurt Hbf→Augsburg Hbf",
        ])

    def test_things_deleted_with_something_else_are_not_listed(self):
        Meal.objects.create(day=self.day, name="Lunch spot", meal_type="lunch")
        TripActivity.objects.create(trip=self.trip, day=self.day, title="Tour")
        TripChange.objects.all().delete()
        self.day.delete()
        self.assertEqual(self.summaries(), ["Removed Day 1"])

    def test_deleting_a_whole_trip_records_nothing(self):
        self.trip.delete()  # admin-only hard delete; cascades would otherwise name a missing trip
        self.assertFalse(TripChange.objects.exists())

    def test_batch_writes_one_line(self):
        with acting_as(self.ed), changes.batch("Applied tidy suggestions", trip=self.trip):
            for n in range(3):
                Meal.objects.create(day=self.day, name=f"Place {n}", meal_type="lunch")
        change = TripChange.objects.get()
        self.assertEqual((change.summary, change.actor), ("Applied tidy suggestions (3 changes)", self.ed))

    def test_actor_comes_from_the_request(self):
        private = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, private, ignore_errors=True)
        confirmation = Confirmation.attach_number(self.trip, "DB-1", self.leg)
        TripChange.objects.all().delete()
        self.client.force_login(self.ed)
        with override_settings(PRIVATE_MEDIA_ROOT=private):
            self.client.post(reverse("trips:confirmation_file_add", args=[self.trip.pk, confirmation.pk]),
                             {"files": SimpleUploadedFile("t.pdf", b"%PDF-1.4\n%%EOF\n")})
        change = TripChange.objects.get()
        self.assertEqual((change.summary, change.actor), ("Added t.pdf to confirmation DB-1", self.ed))

    def test_scripts_have_no_actor(self):
        Meal.objects.create(day=self.day, name="Somewhere", meal_type="lunch")
        self.assertIsNone(TripChange.objects.get().actor)


class DigestTests(ChangeFixture):
    def change(self, actor, summary="Changed something"):
        return TripChange.objects.create(trip=self.trip, actor=actor, kind="changed", summary=summary)

    def digest_notes(self, user):
        return Notification.objects.filter(user=user, notification_type__name="trip_changed")

    def test_one_digest_per_person_without_their_own_changes(self):
        self.change(self.ed, "Changed A")
        self.change(self.vi, "Changed B")
        call_command("send_trip_digests", stdout=io.StringIO())
        ed_note = self.digest_notes(self.ed).get()
        self.assertIn("Vi: Changed B", ed_note.message)
        self.assertNotIn("Changed A", ed_note.message)
        self.assertIn("1 change to “Bavaria”", ed_note.title)
        co_note = self.digest_notes(self.co).get()
        self.assertIn("Ed: Changed A", co_note.message)
        self.assertIn("Vi: Changed B", co_note.message)
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["co@example.com", "ed@example.com", "vi@example.com"])

    def test_muted_and_inactive_people_are_skipped(self):
        TripGrant.objects.filter(user=self.vi).update(notify_changes=False)
        User.objects.filter(pk=self.co.pk).update(is_active=False)
        self.change(self.ed)
        call_command("send_trip_digests", stdout=io.StringIO())
        self.assertFalse(self.digest_notes(self.vi).exists())
        self.assertFalse(self.digest_notes(self.co).exists())

    def test_nothing_changed_nothing_sent_and_never_twice(self):
        out = io.StringIO()
        call_command("send_trip_digests", stdout=out)
        self.assertIn("No changes", out.getvalue())
        self.change(self.ed)
        call_command("send_trip_digests", stdout=io.StringIO())
        call_command("send_trip_digests", stdout=io.StringIO())
        self.assertEqual(self.digest_notes(self.vi).count(), 1)

    def test_one_digest_per_trip(self):
        other = Trip.objects.create(name="Rome", start_date=date(2027, 5, 1), end_date=date(2027, 5, 2))
        TripGrant.objects.create(trip=other, user=self.vi, role=TripRole.VIEWER)
        self.change(self.ed)
        TripChange.objects.create(trip=other, actor=self.ed, kind="added", summary="Added X")
        call_command("send_trip_digests", stdout=io.StringIO())
        self.assertEqual(sorted(n.title for n in self.digest_notes(self.vi)),
                         ["1 change to “Bavaria”", "1 change to “Rome”"])

    def test_dry_run_sends_and_marks_nothing(self):
        self.change(self.ed)
        out = io.StringIO()
        call_command("send_trip_digests", "--dry-run", stdout=out)
        self.assertIn("would be sent", out.getvalue())
        self.assertFalse(Notification.objects.filter(notification_type__name="trip_changed").exists())
        self.assertTrue(TripChange.objects.filter(digest_sent_at=None).exists())

    def test_long_lists_are_cut(self):
        for n in range(35):
            self.change(self.ed, f"Changed {n}")
        call_command("send_trip_digests", stdout=io.StringIO())
        self.assertIn("…and 5 more", self.digest_notes(self.vi).get().message)


class UrgentTests(ChangeFixture):
    def move(self, today):
        with mock.patch("apps.trips.changes.timezone.localdate", return_value=today), acting_as(self.ed), \
                self.captureOnCommitCallbacks(execute=True):
            self.leg.departure_at = datetime(2027, 9, 19, 8, 30, tzinfo=dt_timezone.utc)
            self.leg.save()

    def test_time_change_within_a_week_tells_everyone_now(self):
        self.move(date(2027, 9, 15))
        notes = Notification.objects.filter(notification_type__name="trip_changed")
        self.assertEqual(sorted(n.user.username for n in notes), ["co", "vi"])  # not Ed, who made it
        note = notes.get(user=self.vi)
        self.assertEqual(note.title, "Time change: DB ICE 511 Frankfurt Hbf → Augsburg Hbf")
        self.assertIn("now departs Sun Sep 19 10:30 AM CEST (was Sun Sep 19 10:00 AM CEST)", note.message)
        self.assertTrue(note.action_url.endswith(f"#leg-{self.leg.pk}"))

    def test_further_off_waits_for_the_digest(self):
        self.move(date(2027, 8, 1))
        self.assertFalse(Notification.objects.filter(notification_type__name="trip_changed").exists())
        self.assertTrue(TripChange.objects.exists())

    def test_muted_people_get_no_urgent_email(self):
        TripGrant.objects.filter(user=self.vi).update(notify_changes=False)
        self.move(date(2027, 9, 15))
        self.assertFalse(Notification.objects.filter(user=self.vi, notification_type__name="trip_changed").exists())


class MuteTests(ChangeFixture):
    def test_menu_switch(self):
        self.client.force_login(self.vi)
        page = reverse("trips:trip_detail", args=[self.trip.pk])
        self.assertContains(self.client.get(page), "Stop emails about this trip")
        self.client.post(reverse("trips:trip_notify", args=[self.trip.pk]), {"on": "0"})
        self.assertFalse(TripGrant.objects.get(user=self.vi).notify_changes)
        self.assertContains(self.client.get(page), "Email me about changes to this trip")
        self.client.post(reverse("trips:trip_notify", args=[self.trip.pk]), {"on": "1"})
        self.assertTrue(TripGrant.objects.get(user=self.vi).notify_changes)

    def test_no_grant_is_a_404(self):
        stranger = User.objects.create_user("st", "st@example.com", "pw-1234-abcd")
        self.client.force_login(stranger)
        self.assertEqual(self.client.post(reverse("trips:trip_notify", args=[self.trip.pk]), {"on": "0"}).status_code,
                         404)
