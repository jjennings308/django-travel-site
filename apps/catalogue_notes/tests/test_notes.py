"""Notes on catalogue places, activities and events (docs/plans/catalogue-notes.md, N1)."""
from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalQueue, ApprovalStatus
from apps.catalogue_notes.models import CatalogueNote
from apps.catalogue_notes.services import notes_for
from apps.events.models import Event
from apps.locations.models import City, Country, POI
from apps.notifications.models import Notification

User = get_user_model()
APPROVED = ApprovalStatus.APPROVED


class Fixture(TestCase):
    def setUp(self):
        self.staff = User.objects.create_superuser("st", "st@example.com", "pw-1234-abcd")
        self.member = User.objects.create_user("me", "me@example.com", "pw-1234-abcd")
        self.other = User.objects.create_user("ot", "ot@example.com", "pw-1234-abcd")
        de = Country.objects.create(name="Germany", slug="germany", iso_code="DE", iso3_code="DEU", continent="Europe",
                                    approval_status=APPROVED)
        munich = City.objects.create(name="Munich", slug="munich", country=de, latitude=0, longitude=0,
                                     approval_status=APPROVED)
        self.wiesn = POI.objects.create(name="Theresienwiese", slug="theresienwiese", city=munich, latitude=0,
                                        longitude=0, approval_status=APPROVED)
        category, _ = ActivityCategory.objects.get_or_create(name="Festival", defaults={"slug": "festival"})
        self.okto = Activity.objects.create(name="Oktoberfest", slug="oktoberfest", category=category, description="d",
                                            venue=self.wiesn, visibility="public", approval_status=APPROVED,
                                            created_by=self.staff)
        self.okto27 = Event.objects.create(name="Oktoberfest 2027", slug="oktoberfest-2027", description="d",
                                           start_date=date(2027, 9, 18), end_date=date(2027, 10, 3),
                                           related_activity=self.okto, category=category, poi=self.wiesn, city=munich, approval_status=APPROVED,
                                           created_by=self.staff)

    def note(self, **values):
        values.setdefault("approval_status", APPROVED)
        values.setdefault("text", "x")
        return CatalogueNote.objects.create(**values)

    def fragment(self, kind, slug, user=None):
        if user:
            self.client.force_login(user)
        else:
            self.client.logout()
        return self.client.get(reverse("catalogue_notes:for_target", args=[kind, slug])).content.decode()


class ModelTests(Fixture):
    def test_one_target_only(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            CatalogueNote.objects.create(text="x", poi=self.wiesn, activity=self.okto)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CatalogueNote.objects.create(text="x")

    def test_labels(self):
        note = self.note(poi=self.wiesn, closed_weekdays=[1, 0], book_ahead=3, book_ahead_unit="months")
        self.assertEqual((note.closed_label, note.book_ahead_label), ("Closed Mon, Tue", "Book 3 months ahead"))
        note.book_ahead, note.book_ahead_unit = 1, "weeks"
        self.assertEqual(note.book_ahead_label, "Book 1 week ahead")
        self.assertEqual(note.get_absolute_url(), "/locations/pois/theresienwiese/#good-to-know")

    def test_an_approval_queue_lists_them(self):
        self.assertTrue(ApprovalQueue.objects.filter(slug="catalogue-notes").exists())


class InheritanceTests(Fixture):
    def test_an_event_shows_its_own_then_its_activitys_then_its_venues(self):
        venue = self.note(poi=self.wiesn, text="Cash only in the tents")
        activity = self.note(activity=self.okto, text="Tents need reservations", book_ahead=8)
        own = self.note(event=self.okto27, text="Opening Saturday is the busiest")
        notes = notes_for(self.okto27)
        self.assertEqual(notes, [own, activity, venue])
        self.assertEqual([n.from_name for n in notes], [None, "Oktoberfest", "Theresienwiese"])
        self.assertEqual(notes_for(self.okto), [activity, venue])
        self.assertEqual(notes_for(self.wiesn), [venue])


class AddingTests(Fixture):
    def add(self, user, **data):
        self.client.force_login(user)
        return self.client.post(reverse("catalogue_notes:add", args=["poi", "theresienwiese"]),
                                {"tone": "warning", "text": "Closed for setup in early September", "checked_on": "2026-10-26",
                                 "book_ahead_unit": "months", **data})

    def test_a_members_note_waits_for_review_and_staff_hear_of_it(self):
        response = self.add(self.member, closed_weekdays=["0", "1"])
        self.assertEqual(response["Location"], "/locations/pois/theresienwiese/#good-to-know")
        note = CatalogueNote.objects.get()
        self.assertEqual((note.approval_status, note.created_by, note.submitted_by, note.closed_weekdays),
                         (ApprovalStatus.PENDING, self.member, self.member, [0, 1]))
        self.assertTrue(Notification.objects.filter(user=self.staff, title__contains="Theresienwiese").exists())

    def test_staff_notes_are_published_at_once(self):
        self.add(self.staff)
        self.assertEqual(CatalogueNote.objects.get().approval_status, APPROVED)

    def test_only_published_items_take_notes(self):
        self.wiesn.approval_status = ApprovalStatus.PENDING
        self.wiesn.save()
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("catalogue_notes:add", args=["poi", "theresienwiese"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("catalogue_notes:add", args=["nope", "x"])).status_code, 404)


class VisibilityTests(Fixture):
    def test_pending_notes_are_their_writers_own(self):
        self.note(poi=self.wiesn, text="Published one")
        self.note(poi=self.wiesn, text="Pending one", approval_status=ApprovalStatus.PENDING, created_by=self.member)
        anonymous = self.fragment("poi", "theresienwiese")
        self.assertIn("Published one", anonymous)
        self.assertNotIn("Pending one", anonymous)
        self.assertIn("Log in to add a note", anonymous)
        self.assertNotIn("Pending one", self.fragment("poi", "theresienwiese", self.other))
        mine = self.fragment("poi", "theresienwiese", self.member)
        self.assertIn("Pending one", mine)
        self.assertIn("waiting for review", mine)
        self.assertIn("Pending one", self.fragment("poi", "theresienwiese", self.staff))

    def test_the_card_is_on_every_detail_page(self):
        for url, kind, slug in ((reverse("locations:poi_detail", args=["theresienwiese"]), "poi", "theresienwiese"),
                                (reverse("activities:activity_detail", args=["oktoberfest"]), "activity", "oktoberfest"),
                                (reverse("events:event_detail", args=["oktoberfest-2027"]), "event", "oktoberfest-2027")):
            with self.subTest(kind=kind):
                self.client.force_login(self.member)
                html = self.client.get(url).content.decode()
                self.assertIn(reverse("catalogue_notes:for_target", args=[kind, slug]), html)
                self.assertIn('id="good-to-know"', html)


class EditingTests(Fixture):
    def test_writer_until_approved_staff_always(self):
        pending = self.note(poi=self.wiesn, approval_status=ApprovalStatus.PENDING, created_by=self.member)
        approved = self.note(poi=self.wiesn, created_by=self.member)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("catalogue_notes:edit", args=[pending.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("catalogue_notes:edit", args=[approved.pk])).status_code, 403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("catalogue_notes:edit", args=[pending.pk])).status_code, 403)
        self.client.force_login(self.staff)
        self.client.post(reverse("catalogue_notes:delete", args=[approved.pk]))
        self.assertFalse(CatalogueNote.objects.filter(pk=approved.pk).exists())

    def test_a_rejected_note_goes_back_for_review_when_edited(self):
        note = self.note(poi=self.wiesn, approval_status=ApprovalStatus.REJECTED, created_by=self.member)
        self.client.force_login(self.member)
        self.client.post(reverse("catalogue_notes:edit", args=[note.pk]),
                         {"tone": "tip", "text": "Better wording", "checked_on": "2026-10-26", "book_ahead_unit": "months"})
        note.refresh_from_db()
        self.assertEqual((note.text, note.approval_status), ("Better wording", ApprovalStatus.PENDING))

    def test_reporting_tells_staff(self):
        note = self.note(poi=self.wiesn, text="Open daily", created_by=self.staff)
        self.client.force_login(self.member)
        response = self.client.post(reverse("catalogue_notes:report", args=[note.pk]), {"reason": "Closed Mondays now"})
        self.assertEqual(response["Location"], note.get_absolute_url())
        self.assertTrue(Notification.objects.filter(user=self.staff, title__contains="Theresienwiese").exists())


class ApprovalTests(Fixture):
    def test_staff_approve_a_note_on_the_review_page_and_its_writer_hears(self):
        from django.contrib.contenttypes.models import ContentType
        note = self.note(poi=self.wiesn, text="Cash only", approval_status=ApprovalStatus.PENDING, created_by=self.member)
        note.submit_for_review(self.member)
        url = reverse("approval_system:review_item", args=[ContentType.objects.get_for_model(CatalogueNote).pk, note.pk])
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(url, {"action": "approve", "notes": ""})
        note.refresh_from_db()
        self.assertEqual(note.approval_status, APPROVED)
        self.assertIn("Cash only", self.fragment("poi", "theresienwiese"))  # now everyone sees it
        self.assertTrue(Notification.objects.filter(user=self.member).exists())
