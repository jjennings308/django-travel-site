"""Warnings from catalogue notes: closed days and book-ahead dates (docs/plans/catalogue-notes.md, N3)."""
import re
from datetime import date, time
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.catalogue_notes.models import CatalogueNote
from apps.locations.models import City, Country, POI
from apps.trips.models import BookingTask, Day, Meal, Trip, TripActivity, TripGrant, TripHiddenNote, TripRole

User = get_user_model()
APPROVED = ApprovalStatus.APPROVED
TODAY = "apps.trips.views.django_timezone.localdate"


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Utah", start_date=date(2027, 9, 20), end_date=date(2027, 9, 22),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        us = Country.objects.create(name="United States", slug="us", iso_code="US", iso3_code="USA",
                                    continent="North America", approval_status=APPROVED)
        moab = City.objects.create(name="Moab", slug="moab", country=us, latitude=0, longitude=0, approval_status=APPROVED)
        self.diner = POI.objects.create(name="Moab Diner", slug="moab-diner", city=moab, latitude=0, longitude=0,
                                        approval_status=APPROVED)
        self.arches = POI.objects.create(name="Arches", slug="arches", city=moab, latitude=0, longitude=0,
                                         approval_status=APPROVED)
        self.monday = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 20))  # a Monday
        self.wednesday = Day.objects.create(trip=self.trip, day_number=3, date=date(2027, 9, 22))
        self.closed = CatalogueNote.objects.create(poi=self.diner, text="Family-run.", closed_weekdays=[0, 1],
                                                   approval_status=APPROVED)
        self.entry = CatalogueNote.objects.create(poi=self.arches, tone="critical", text="Timed entry needed.",
                                                  book_ahead=3, book_ahead_unit="months",
                                                  booking_url="https://www.recreation.gov/", approval_status=APPROVED)
        self.visit = TripActivity.objects.create(trip=self.trip, day=self.monday, kind="entry", title="Arches",
                                                 poi=self.arches, start_time=time(8))

    def page(self, today):
        self.client.force_login(self.editor)
        with mock.patch(TODAY, return_value=today):
            return self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))

    @staticmethod
    def banner(html):
        found = re.search(r'id="needs-attention">(.*?)</p>', html, re.S)
        return found.group(1) if found else ""


class ClosedTests(Fixture):
    def test_a_meal_on_a_closed_weekday_warns_and_counts(self):
        monday_meal = Meal.objects.create(day=self.monday, name="Diner dinner", meal_type="dinner", poi=self.diner)
        Meal.objects.create(day=self.wednesday, name="Diner again", meal_type="dinner", poi=self.diner)
        response = self.page(date(2027, 1, 1))
        html = response.content.decode()
        self.assertEqual([m.pk for m in response.context["closed_items"]], [monday_meal.pk])
        self.assertIn("⚠ Moab Diner is closed on Mondays", html)
        self.assertEqual(html.count("data-closed-warning"), 1)  # not the Wednesday one
        self.assertIn("1 closed on its day", self.banner(html))
        days = {d.day_number: d for d in response.context["days"]}
        self.assertGreaterEqual(days[1].attention, 1)
        self.assertEqual(days[3].attention, 0)

    def test_a_hidden_note_doesnt_warn(self):
        Meal.objects.create(day=self.monday, name="Diner dinner", meal_type="dinner", poi=self.diner)
        TripHiddenNote.objects.create(trip=self.trip, note=self.closed)
        html = self.page(date(2027, 1, 1)).content.decode()
        self.assertNotIn("data-closed-warning", html)
        self.assertNotIn("closed on its day", self.banner(html))


class BookAheadTests(Fixture):
    def test_the_book_by_date_and_when_it_counts(self):
        early = self.page(date(2027, 1, 1)).content.decode()
        self.assertIn("Book by Sun Jun 20, 2027", early)  # Sep 20 minus 3 months
        self.assertNotIn("to book ahead", self.banner(early))  # months away: shown, not pressing
        soon = self.page(date(2027, 6, 1)).content.decode()
        self.assertIn("1 to book ahead", self.banner(soon))
        late = self.page(date(2027, 7, 1)).content.decode()
        self.assertIn("— overdue", late)

    def test_add_as_a_todo_pre_fills_and_then_covers_it(self):
        html = self.page(date(2027, 6, 1)).content.decode()
        link = re.search(r'href="([^"]+)" data-note-todo', html).group(1).replace("&amp;", "&")
        self.assertIn(f"activity={self.visit.pk}", link)
        form = self.client.get(link).context["form"]
        self.assertEqual((form.initial["title"], form.initial["due"]), ("Book ahead: Arches", date(2027, 6, 20)))
        self.assertIn("recreation.gov", form.initial["notes"])
        self.client.post(reverse("trips:task_new", args=[self.trip.pk]), {
            "title": "Book ahead: Arches", "kind": "book", "priority": "2", "due": "2027-06-20", "due_note": "",
            "day": self.monday.pk, "leg": "", "stay": "", "activity": self.visit.pk, "confirmation": "", "order": "",
            "notes": "https://www.recreation.gov/", "from_note": self.entry.pk})
        task = BookingTask.objects.get()
        self.assertEqual(task.note_ids(), {self.entry.pk})
        self.assertNotIn("Catalogue note", task.visible_notes)
        after = self.page(date(2027, 6, 1)).content.decode()
        self.assertNotIn("to book ahead", self.banner(after))
        self.assertIn("a to-do covers it", after)

    def test_the_booklet_prints_the_warnings(self):
        Meal.objects.create(day=self.monday, name="Diner dinner", meal_type="dinner", poi=self.diner)
        self.client.force_login(self.editor)
        with mock.patch(TODAY, return_value=date(2027, 6, 1)), \
                mock.patch("apps.trips.pdf.render_pdf", side_effect=lambda html, base_url: html.encode()):
            body = self.client.get(reverse("trips:trip_pdf", args=[self.trip.pk])).content.decode()
        self.assertIn("Moab Diner is closed on Mondays.", body)
        self.assertIn("Book by Sun Jun 20, 2027", body)
