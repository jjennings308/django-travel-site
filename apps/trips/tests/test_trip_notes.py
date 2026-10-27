"""Catalogue notes on a trip's linked items, and "Not for this trip" (docs/plans/catalogue-notes.md, N2)."""
from datetime import date, time
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.catalogue_notes.models import CatalogueNote
from apps.locations.models import City, Country, POI
from apps.trips.models import Day, Meal, Section, Trip, TripActivity, TripGrant, TripHiddenNote, TripRole

User = get_user_model()
APPROVED = ApprovalStatus.APPROVED


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 18), end_date=date(2027, 9, 20),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        de = Country.objects.create(name="Germany", slug="de", iso_code="DE", iso3_code="DEU", continent="Europe",
                                    approval_status=APPROVED)
        city = City.objects.create(name="Marburg", slug="marburg", country=de, latitude=0, longitude=0,
                                   approval_status=APPROVED)
        self.castle = POI.objects.create(name="Marburg Castle", slug="marburg-castle", city=city, latitude=0,
                                         longitude=0, approval_status=APPROVED)
        self.franco = POI.objects.create(name="Da Franco", slug="da-franco", city=city, latitude=0, longitude=0,
                                         approval_status=APPROVED)
        category, _ = ActivityCategory.objects.get_or_create(name="Sightseeing", defaults={"slug": "sightseeing"})
        self.walk = Activity.objects.create(name="Castle walk", slug="castle-walk", category=category, description="x",
                                            venue=self.castle, visibility="public", approval_status=APPROVED)
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 18))
        self.meal = Meal.objects.create(day=self.day, name="Da Franco", meal_type="dinner", poi=self.franco,
                                        reserved_time=time(19, 30))
        self.tour = TripActivity.objects.create(trip=self.trip, day=self.day, kind="entry", title="Castle museum",
                                                poi=self.castle)
        self.section = Section.objects.create(day=self.day, section_type="note", title="The walk", order=1,
                                              activity=self.walk, content={"paragraphs": ["Up the hill."]})

    def note(self, **values):
        values.setdefault("approval_status", APPROVED)
        return CatalogueNote.objects.create(**values)

    def page(self, user):
        self.client.force_login(user)
        with mock.patch("apps.trips.views.django_timezone.localdate", return_value=date(2027, 9, 1)):
            return self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()

    @staticmethod
    def block(html, anchor):
        start = html.index(anchor)
        return html[start:start + 4000]


class ShownTests(Fixture):
    def test_each_linked_item_shows_its_places_notes(self):
        self.note(poi=self.franco, text="Closed early on Sundays", closed_weekdays=[0])
        self.note(poi=self.castle, tone="warning", text="Museum: cash only")
        self.note(activity=self.walk, text="Steep cobbles; good shoes", book_ahead=2, book_ahead_unit="weeks")
        self.note(poi=self.franco, text="Still waiting for review", approval_status=ApprovalStatus.PENDING)
        html = self.page(self.viewer)
        meal = self.block(html, f'id="meal-{self.meal.pk}"')
        self.assertIn("Closed early on Sundays", meal)
        self.assertIn("Closed Mon", meal)
        self.assertIn("From Da Franco", meal)
        self.assertNotIn("Still waiting for review", html)  # approved only
        self.assertIn("Museum: cash only", self.block(html, f'id="activity-{self.tour.pk}"'))
        walk = html[html.index("The walk"):]
        self.assertIn("Steep cobbles; good shoes", walk[:4000])
        self.assertIn("Book 2 weeks ahead", walk[:4000])
        self.assertIn("callout-warning", self.block(html, f'id="activity-{self.tour.pk}"'))
        self.assertLess(walk.index("Steep cobbles"), walk.index("Museum: cash only"))  # the activity's, then its venue's
        self.assertNotIn("data-hide-note", html)  # viewers can't hide


class HidingTests(Fixture):
    def test_editors_hide_a_note_on_this_trip_only_and_bring_it_back(self):
        note = self.note(poi=self.franco, text="Closed early on Sundays")
        other = Trip.objects.create(name="Other", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        TripHiddenNote.objects.create(trip=other, note=note)  # hidden elsewhere: still shown here
        html = self.page(self.editor)
        self.assertIn("Closed early on Sundays", self.block(html, f'id="meal-{self.meal.pk}"'))
        hide = reverse("trips:trip_note_hide", args=[self.trip.pk, note.pk])
        self.assertIn(f'action="{hide}"', html)
        self.client.post(hide, {"next": reverse("trips:trip_detail", args=[self.trip.pk])})
        self.assertTrue(TripHiddenNote.objects.filter(trip=self.trip, note=note).exists())
        html = self.page(self.editor)
        meal = self.block(html, f'id="meal-{self.meal.pk}"')
        self.assertNotIn('data-trip-note="', meal[:meal.find("data-hidden-notes")])
        self.assertIn("data-hidden-notes", meal)  # editors can show it again
        self.assertNotIn("Closed early on Sundays", self.page(self.viewer))
        self.client.force_login(self.editor)
        self.client.post(hide, {"show": "1"})
        self.assertFalse(TripHiddenNote.objects.filter(trip=self.trip, note=note).exists())

    def test_only_editors_may_hide(self):
        note = self.note(poi=self.franco, text="x")
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(reverse("trips:trip_note_hide", args=[self.trip.pk, note.pk])).status_code, 403)
        self.assertFalse(TripHiddenNote.objects.exists())

    def test_the_booklet_skips_hidden_notes(self):
        shown = self.note(poi=self.castle, text="Museum: cash only")
        hidden = self.note(poi=self.castle, text="Not for us")
        TripHiddenNote.objects.create(trip=self.trip, note=hidden)
        self.client.force_login(self.viewer)
        with mock.patch("apps.trips.pdf.render_pdf", side_effect=lambda html, base_url: html.encode()):
            body = self.client.get(reverse("trips:trip_pdf", args=[self.trip.pk])).content.decode()
        self.assertIn(shown.text, body)
        self.assertNotIn(hidden.text, body)
