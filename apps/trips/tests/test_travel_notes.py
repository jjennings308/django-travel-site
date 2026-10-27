"""Logistics tables give way to travel notes (docs/plans/edit-by-day.md, E6)."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.trips.models import Day, Section, Trip, TripGrant, TripRole

User = get_user_model()


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 17), end_date=date(2027, 9, 20),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 17))
        self.table = Section.objects.create(
            day=self.day, section_type=Section.Type.LOGISTICS_TABLE, title="Getting to the fair",
            content={"columns": ["What", "Cost"], "rows": [["Bayern Ticket", "€29"], ["Seat reservation", "€5"]]})
        self.edit_url = reverse("trips:section_edit", args=[self.trip.pk, self.day.pk, self.table.pk])
        self.convert_url = reverse("trips:section_to_travel_notes", args=[self.trip.pk, self.day.pk, self.table.pk])


class DayPageTests(Fixture):
    def test_add_to_this_day_offers_travel_notes_and_no_logistics_table(self):
        self.client.force_login(self.editor)
        html = self.client.get(reverse("trips:day_edit", args=[self.trip.pk, self.day.pk])).content.decode()
        add = html[html.index('id="add"'):html.index('id="on-this-day"')]
        labels = [label for label in ("+ Note<", "+ Phase", "+ Callout", "+ Free text", "+ Travel notes",
                                      "+ Choose your adventure") if label in add]
        # Phases, callouts and free text are notes now (day-first plan P3).
        self.assertEqual(labels, ["+ Note<", "+ Travel notes", "+ Choose your adventure"])
        self.assertNotIn("Logistics table", add)
        self.assertIn(reverse("trips:section_create", args=[self.trip.pk, self.day.pk, "travel"]), add)


class MakeTravelNotesTests(Fixture):
    def test_the_table_page_offers_it_and_it_keeps_the_rows(self):
        self.client.force_login(self.editor)
        self.assertContains(self.client.get(self.edit_url), "data-make-travel-notes")
        response = self.client.post(self.convert_url)
        self.assertEqual(response["Location"], self.edit_url)
        self.table.refresh_from_db()
        self.assertEqual(self.table.section_type, Section.Type.TRAVEL)
        self.assertEqual(self.table.content["rows"], [["Bayern Ticket", "€29"], ["Seat reservation", "€5"]])
        self.assertEqual(self.table.title, "Getting to the fair")
        html = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        self.assertIn("Bayern Ticket", html)  # still shown on the trip page, as reference rows

    def test_only_editors_and_only_tables(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(self.convert_url).status_code, 403)
        self.assertEqual(self.client.get(self.convert_url).status_code, 405)
        note = Section.objects.create(day=self.day, section_type=Section.Type.FREE_TEXT, content={"text": "x"})
        self.client.force_login(self.editor)
        url = reverse("trips:section_to_travel_notes", args=[self.trip.pk, self.day.pk, note.pk])
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_an_old_table_still_renders_and_edits(self):
        self.client.force_login(self.editor)
        self.assertContains(self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])), "Bayern Ticket")
        self.assertEqual(self.client.get(self.edit_url).status_code, 200)
