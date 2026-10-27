"""Tidy: move a trip's callout about a linked place, activity or event to the catalogue
(docs/plans/catalogue-notes.md, N5)."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.catalogue_notes.models import CatalogueNote
from apps.events.models import Event
from apps.locations.models import City, Country, POI
from apps.notifications.models import Notification
from apps.trips import tidying
from apps.trips.models import Day, Meal, Section, TidyDismissal, Trip, TripActivity, TripGrant, TripRole

User = get_user_model()
APPROVED = ApprovalStatus.APPROVED


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 18), end_date=date(2027, 9, 22),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        de = Country.objects.create(name="Germany", slug="de", iso_code="DE", iso3_code="DEU", continent="Europe",
                                    approval_status=APPROVED)
        city = City.objects.create(name="Marburg", slug="marburg", country=de, latitude=0, longitude=0,
                                   approval_status=APPROVED)
        self.castle = POI.objects.create(name="Marburg Castle", slug="marburg-castle", city=city, latitude=0,
                                         longitude=0, approval_status=APPROVED)
        self.wiesn = POI.objects.create(name="Theresienwiese", slug="theresienwiese", city=city, latitude=0,
                                        longitude=0, approval_status=APPROVED)
        category, _ = ActivityCategory.objects.get_or_create(name="Festival", defaults={"slug": "festival"})
        okto = Activity.objects.create(name="Oktoberfest", slug="oktoberfest", category=category, description="d",
                                       venue=self.wiesn, visibility="public", approval_status=APPROVED)
        self.okto27 = Event.objects.create(name="Oktoberfest 2027", slug="oktoberfest-2027", description="d",
                                           category=category, start_date=date(2027, 9, 18),
                                           end_date=date(2027, 10, 3), city=city, related_activity=okto,
                                           poi=self.wiesn, approval_status=APPROVED)
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 18))
        self.other_day = Day.objects.create(trip=self.trip, day_number=2, date=date(2027, 9, 19))
        TripActivity.objects.create(trip=self.trip, day=self.day, kind="entry", title="Castle museum",
                                    poi=self.castle)

    def callout(self, text, day=None, title="Heads up", tone="warning"):
        return Section.objects.create(day=day or self.day, section_type="note", title=title,
                                      content={"tone": tone, "paragraphs": [text]})

    def found(self):
        return [s for s in tidying.suggestions(self.trip) if s.kind == "catalogue_note"]


class DetectTests(Fixture):
    def test_only_a_callout_naming_something_linked_that_day(self):
        self.callout("Marburg Castle's museum is cash only.")
        self.callout("Marburg Castle again, but on a day with nothing linked.", day=self.other_day)
        self.callout("Olga is arranged by John.")
        Section.objects.create(day=self.day, section_type="note", title="Marburg Castle",
                               content={"paragraphs": ["Marburg Castle is up the hill."]})
        found = self.found()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].change["target"]["name"], "Marburg Castle")
        self.assertIn("note about Marburg Castle", found[0].after)
        self.assertEqual(found[0].confidence, "low")  # review only

    def test_an_events_activity_and_venue_count_and_capitals_and_accents_dont(self):
        Meal.objects.create(day=self.other_day, name="Tent lunch", meal_type="lunch")
        Section.objects.create(day=self.other_day, section_type="note", title="Wiesn", event=self.okto27,
                               content={"paragraphs": ["Beer."]})
        self.callout("THERESIENWIESE: cash only in the tents.", day=self.other_day)
        self.assertEqual([s.change["target"]["kind"] for s in self.found()], ["poi"])


class ApplyTests(Fixture):
    def apply(self, user):
        found = self.found()
        return tidying.apply(self.trip, found, {s.key: "to_catalogue" for s in found}, user)

    def test_a_member_submits_a_pending_note_and_the_callout_goes(self):
        staff = User.objects.create_superuser("st", "st@example.com", "pw-1234-abcd")
        section = self.callout("Marburg Castle museum has no ATM nearby.", title="⚠ Cash only", tone="critical")
        applied, skipped = self.apply(self.editor)
        self.assertEqual((len(applied), skipped), (1, []))
        note = CatalogueNote.objects.get()
        self.assertEqual((note.poi, note.tone, note.created_by, note.approval_status),
                         (self.castle, "critical", self.editor, ApprovalStatus.PENDING))
        self.assertEqual(note.text, "Cash only: Marburg Castle museum has no ATM nearby.")
        self.assertFalse(Section.objects.filter(pk=section.pk).exists())
        self.assertTrue(Notification.objects.filter(user=staff).exists())  # as for any submission

    def test_staff_publish_it_at_once(self):
        staff = User.objects.create_user("st", "st@example.com", "pw-1234-abcd", is_staff=True)
        self.callout("Closes at 4 pm in winter.", title="Marburg Castle", tone="info")
        self.apply(staff)
        note = CatalogueNote.objects.get()
        self.assertEqual((note.approval_status, note.tone, note.text), (APPROVED, "tip", "Closes at 4 pm in winter."))

    def test_stale_when_the_callout_changed(self):
        section = self.callout("Marburg Castle: cash only.")
        found = self.found()
        section.content = {"tone": "warning", "text": "Marburg Castle: cards now."}
        section.save()
        applied, skipped = tidying.apply(self.trip, found, {found[0].key: "to_catalogue"}, self.editor)
        self.assertEqual((applied, len(skipped)), ([], 1))
        self.assertFalse(CatalogueNote.objects.exists())

    def test_the_page_applies_and_dismisses(self):
        self.callout("Marburg Castle: cash only.")
        self.client.force_login(self.editor)
        url = reverse("trips:trip_tidy", args=[self.trip.pk])
        self.assertContains(self.client.get(url), "Move it to the catalogue as a note on Marburg Castle")
        key = self.found()[0].key
        self.client.post(url, {"dismiss": key})
        self.assertTrue(TidyDismissal.objects.filter(trip=self.trip, key=key).exists())
        self.assertEqual(self.found(), [])
        TidyDismissal.objects.all().delete()
        self.client.post(url, {f"pick-{key}": "on", f"act-{key}": "to_catalogue"})
        self.assertEqual(CatalogueNote.objects.get().approval_status, ApprovalStatus.PENDING)
