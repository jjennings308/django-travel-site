"""Trip items linked to catalogue events, and the notes they bring (docs/plans/catalogue-notes.md, N4)."""
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.catalogue_notes.models import CatalogueNote
from apps.events.models import Event
from apps.locations.models import City, Country, POI
from apps.trips import catalogue_counts
from apps.trips.forms import SectionForm, TripActivityForm, catalogue_events
from apps.trips.models import Day, Section, TidyDismissal, Trip, TripActivity, TripGrant, TripRole

User = get_user_model()
APPROVED = ApprovalStatus.APPROVED


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Bavaria", start_date=date(2027, 9, 18), end_date=date(2027, 9, 25),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        de = Country.objects.create(name="Germany", slug="de", iso_code="DE", iso3_code="DEU", continent="Europe",
                                    approval_status=APPROVED)
        self.munich = City.objects.create(name="Munich", slug="munich", country=de, latitude=0, longitude=0,
                                          approval_status=APPROVED)
        berlin = City.objects.create(name="Berlin", slug="berlin", country=de, latitude=0, longitude=0,
                                     approval_status=APPROVED)
        self.trip.cities.set([self.munich])
        self.wiesn = POI.objects.create(name="Theresienwiese", slug="theresienwiese", city=self.munich, latitude=0,
                                        longitude=0, approval_status=APPROVED)
        category, _ = ActivityCategory.objects.get_or_create(name="Festival", defaults={"slug": "festival"})
        self.okto = Activity.objects.create(name="Oktoberfest", slug="oktoberfest", category=category, description="d",
                                            city=self.munich, venue=self.wiesn, visibility="public",
                                            approval_status=APPROVED)

        def event(name, start, end, city, **extra):
            return Event.objects.create(name=name, slug=name.lower().replace(" ", "-"), description="d", category=category,
                                        start_date=start, end_date=end, city=city,
                                        approval_status=extra.pop("status", APPROVED), **extra)

        self.okto27 = event("Oktoberfest 2027", date(2027, 9, 18), date(2027, 10, 3), self.munich,
                            related_activity=self.okto, poi=self.wiesn)
        self.berlin_fest = event("Berlin Festival", date(2027, 9, 20), date(2027, 9, 21), berlin)
        self.too_late = event("Christmas Market", date(2027, 11, 25), date(2027, 12, 23), self.munich)
        self.pending = event("Pending Fair", date(2027, 9, 19), date(2027, 9, 19), self.munich,
                             status=ApprovalStatus.PENDING)
        self.day = Day.objects.create(trip=self.trip, day_number=4, date=date(2027, 9, 21))


class ChoiceTests(Fixture):
    def test_events_during_the_trip_in_its_cities_first(self):
        self.assertEqual(list(catalogue_events(self.trip)), [self.okto27, self.berlin_fest])
        for form in (SectionForm(instance=Section(day=self.day, section_type="free_text"), trip=self.trip),
                     TripActivityForm(instance=TripActivity(trip=self.trip, day=self.day), trip=self.trip)):
            with self.subTest(form=type(form).__name__):
                self.assertEqual(list(form.fields["event"].queryset), [self.okto27, self.berlin_fest])
                self.assertIn("Oktoberfest 2027 · Sep 18 · Munich", [label for _pk, label in form.fields["event"].choices])


class NotesTests(Fixture):
    def test_an_event_brings_its_own_its_activitys_and_its_venues_notes(self):
        CatalogueNote.objects.create(poi=self.wiesn, text="Cash only in the tents", approval_status=APPROVED)
        CatalogueNote.objects.create(activity=self.okto, text="Reserve a tent table", approval_status=APPROVED)
        CatalogueNote.objects.create(event=self.okto27, text="Opening day is the busiest", approval_status=APPROVED)
        Section.objects.create(day=self.day, section_type="free_text", title="The Wiesn", event=self.okto27,
                               content={"paragraphs": ["Beer."]})
        TripActivity.objects.create(trip=self.trip, day=self.day, kind="table", title="Tent table", event=self.okto27)
        self.client.force_login(self.editor)
        with mock.patch("apps.trips.views.django_timezone.localdate", return_value=date(2027, 9, 1)):
            html = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        section = html[html.index("The Wiesn"):html.index("The Wiesn") + 5000]
        order = [section.index(text) for text in ("Opening day is the busiest", "Reserve a tent table", "Cash only in the tents")]
        self.assertEqual(order, sorted(order))
        self.assertIn(reverse("events:event_detail", args=["oktoberfest-2027"]), section)
        self.assertIn("From Oktoberfest 2027", section)
        self.assertEqual(html.count("Opening day is the busiest"), 2)  # the section and the tent table


class SuggestionTests(Fixture):
    def test_a_section_named_for_the_activity_on_an_event_day_is_offered_the_event(self):
        section = Section.objects.create(day=self.day, section_type="free_text", title="Oktoberfest",
                                         content={"paragraphs": ["Beer."]})
        self.client.force_login(self.editor)
        page = self.client.get(reverse("trips:day_edit", args=[self.trip.pk, self.day.pk]))
        self.assertContains(page, "Looks like the catalogue event")
        link = reverse("trips:catalogue_link", args=[self.trip.pk, self.day.pk, "section", section.pk])
        self.client.post(link, {"target_kind": "event", "target": self.okto27.pk})
        section.refresh_from_db()
        self.assertEqual(section.event, self.okto27)

    def test_not_this_one_and_events_outside_the_trip_are_refused(self):
        section = Section.objects.create(day=self.day, section_type="free_text", title="Oktoberfest",
                                         content={"paragraphs": ["Beer."]})
        self.client.force_login(self.editor)
        link = reverse("trips:catalogue_link", args=[self.trip.pk, self.day.pk, "section", section.pk])
        self.client.post(link, {"target_kind": "event", "target": self.too_late.pk})
        section.refresh_from_db()
        self.assertIsNone(section.event)
        self.client.post(link, {"target_kind": "event", "target": self.okto27.pk, "dismiss": "1"})
        self.assertTrue(TidyDismissal.objects.filter(trip=self.trip, key__contains="event").exists())
        self.assertNotContains(self.client.get(reverse("trips:day_edit", args=[self.trip.pk, self.day.pk])),
                               "Looks like the catalogue event")


class CountTests(Fixture):
    def test_an_event_counts_its_trips_and_they_count_for_its_activity_and_venue(self):
        Section.objects.create(day=self.day, section_type="free_text", event=self.okto27)
        TripActivity.objects.create(trip=self.trip, day=self.day, kind="table", title="Tent", event=self.okto27)
        other = Trip.objects.create(name="Second", start_date=date(2027, 9, 20), end_date=date(2027, 9, 21))
        TripActivity.objects.create(trip=other, title="Tent", event=self.okto27,
                                    day=Day.objects.create(trip=other, day_number=1, date=date(2027, 9, 20)))
        gone = Trip.objects.create(name="Gone", start_date=date(2027, 9, 20), end_date=date(2027, 9, 21))
        TripActivity.objects.create(trip=gone, title="Tent", event=self.okto27,
                                    day=Day.objects.create(trip=gone, day_number=1, date=date(2027, 9, 20)))
        gone.soft_delete()
        catalogue_counts.recount()
        for obj in (self.okto27, self.okto, self.wiesn):
            obj.refresh_from_db()
            with self.subTest(obj=str(obj)):
                self.assertEqual((obj.trip_count, obj.shown_trip_count), (2, 2))  # each live trip once

    def test_the_event_page_shows_it_only_from_two(self):
        self.client.force_login(self.editor)
        url = reverse("events:event_detail", args=[self.okto27.slug])
        Event.objects.filter(pk=self.okto27.pk).update(trip_count=1)
        self.assertNotContains(self.client.get(url), "On trips")
        Event.objects.filter(pk=self.okto27.pk).update(trip_count=2)
        page = self.client.get(url)
        self.assertContains(page, "On trips")
        self.assertNotContains(page, self.trip.name + "<")
