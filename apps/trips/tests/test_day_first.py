"""Phases, callouts and free text turned into notes, on review (docs/plans/day-first-planning.md, P3)."""
from datetime import date, time
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.trips import day_first, tidying
from apps.trips.forms import NotePayloadForm
from apps.trips.models import Day, Meal, Section, Trip, TripChange, TripGrant, TripRole

User = get_user_model()


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Alps", start_date=date(2027, 9, 18), end_date=date(2027, 9, 21),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 18))
        self.phase = Section.objects.create(day=self.day, section_type="phase", title="Arrive", order=1, icon="🛬",
                                            content={"heading": "Morning — Arrive", "summary": "Land FRA.",
                                                     "highlights": ["Coffee", "Nap"], "source": "docx"})
        self.callout = Section.objects.create(day=self.day, section_type="callout", title="Tip", order=2,
                                              content={"tone": "info", "text": "Pickup is in the terminal"})
        self.prose = Section.objects.create(day=self.day, section_type="free_text", title="Notes", order=3,
                                            content={"paragraphs": ["First.", "Second."]})
        self.table = Section.objects.create(day=self.day, section_type="logistics_table", title="Trains", order=4,
                                            content={"columns": ["Leg"], "rows": [["A → B"]]})


class ConvertTests(Fixture):
    def test_the_plan_saves_nothing(self):
        (day, items), = day_first.plan(self.trip)
        self.assertEqual([item.section for item in items], [self.phase, self.callout, self.prose])
        self.assertEqual(items[0].after, ("Note", ["Morning — Arrive", "Land FRA.", "• Coffee", "• Nap"]))
        self.assertEqual(items[1].after, ("Note", ["Tip (tip)", "Pickup is in the terminal"]))
        self.assertEqual(Section.objects.filter(section_type="note").count(), 0)

    def test_nothing_is_lost(self):
        before = TripChange.objects.count()
        self.assertEqual(day_first.apply(self.trip), 3)
        for section in (self.phase, self.callout, self.prose, self.table):
            section.refresh_from_db()
        self.assertEqual((self.phase.section_type, self.phase.title, self.phase.icon, self.phase.content),
                         ("note", "Morning — Arrive", "🛬",
                          {"tone": "", "paragraphs": ["Land FRA.", "• Coffee", "• Nap"], "source": "docx"}))
        self.assertEqual((self.callout.title, self.callout.content),
                         ("Tip", {"tone": "tip", "paragraphs": ["Pickup is in the terminal"]}))
        self.assertEqual(self.callout.note_style, "info")  # drawn as the old info callout
        self.assertEqual(self.prose.content, {"tone": "", "paragraphs": ["First.", "Second."]})
        self.assertEqual(self.table.section_type, "logistics_table")  # import-only, left alone
        self.assertEqual(TripChange.objects.count(), before + 1)  # one history line
        self.assertEqual(day_first.plan(self.trip), [])
        self.assertEqual(day_first.apply(self.trip), 0)

    def test_only_the_ticked_ones(self):
        self.assertEqual(day_first.apply(self.trip, [self.callout.pk]), 1)
        self.assertEqual(sorted(Section.objects.values_list("section_type", flat=True)),
                         ["free_text", "logistics_table", "note", "phase"])

    def test_the_review_page(self):
        self.client.force_login(self.editor)
        url = reverse("trips:trip_convert", args=[self.trip.pk])
        page = self.client.get(url)
        self.assertContains(page, "data-convert-row", count=3)
        self.assertContains(page, "• Coffee")
        self.client.post(url, {"item": [f"section-{self.phase.pk}", f"section-{self.prose.pk}"]})
        self.assertEqual(Section.objects.filter(section_type="note").count(), 2)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_needs_attention_links_it_for_editors(self):
        self.client.force_login(self.editor)
        trip_page = reverse("trips:trip_detail", args=[self.trip.pk])
        self.assertContains(self.client.get(trip_page), "3 to convert to notes and choices")
        self.client.force_login(self.viewer)
        self.assertNotContains(self.client.get(trip_page), "to convert to notes")
        day_first.apply(self.trip)
        self.client.force_login(self.editor)
        self.assertNotContains(self.client.get(trip_page), "to convert to notes")

    def test_the_command(self):
        out = StringIO()
        call_command("convert_day_first", trip=self.trip.pk, stdout=out)
        self.assertIn("Dry run", out.getvalue())
        self.assertEqual(Section.objects.filter(section_type="note").count(), 0)
        call_command("convert_day_first", trip=self.trip.pk, apply=True, stdout=out)
        self.assertEqual(Section.objects.filter(section_type="note").count(), 3)


    def test_every_trip_with_all(self):
        """Retire-old-section-types S1: --all goes through every live trip; dry run, then apply."""
        other = Trip.objects.create(name="Coast", start_date=date(2027, 10, 1), end_date=date(2027, 10, 2),
                                    created_by=self.editor)
        other_day = Day.objects.create(trip=other, day_number=1, date=date(2027, 10, 1))
        Section.objects.create(day=other_day, section_type="callout", title="Tip", content={"text": "Tides"})
        Section.objects.create(day=other_day, section_type="choose_your_adventure", title="Afternoon",
                               content={"prompt": "Beach or boat?", "options": [{"title": "Beach"}, {"title": "Boat"}]})
        gone = Trip.objects.create(name="Deleted", start_date=date(2027, 1, 1), end_date=date(2027, 1, 1))
        gone_day = Day.objects.create(trip=gone, day_number=1, date=date(2027, 1, 1))
        Section.objects.create(day=gone_day, section_type="phase", title="Old", content={"heading": "Old"})
        gone.soft_delete()
        out = StringIO()
        call_command("convert_day_first", "--all", stdout=out)
        self.assertIn("Alps (trip", out.getvalue())
        self.assertIn("Coast (trip", out.getvalue())
        self.assertNotIn("Deleted", out.getvalue())
        self.assertIn("2 trips, 2 with something to convert, 5 items.", out.getvalue())
        self.assertIn("Dry run", out.getvalue())
        self.assertEqual(Section.objects.filter(section_type="note").count(), 0)
        before = TripChange.objects.count()
        out = StringIO()
        call_command("convert_day_first", "--all", "--apply", stdout=out)
        self.assertIn("converted 5.", out.getvalue())
        self.assertEqual(TripChange.objects.count(), before + 2)  # one history line per trip
        self.assertEqual(Section.objects.filter(day__trip__in=[self.trip, other], section_type__in=[
            "phase", "callout", "free_text", "choose_your_adventure"]).count(), 0)
        self.assertTrue(other.option_groups.filter(prompt="Beach or boat?").exists())
        for trip in (self.trip, other):
            page = Trip.objects.prefetch_related("days__sections", "booking_tasks__options").get(pk=trip.pk)
            for day in page.days.all():
                day.ordered_sections = list(day.sections.all())
            self.assertEqual(day_first.pending_count(page), 0)
        out = StringIO()
        call_command("convert_day_first", "--all", stdout=out)
        self.assertIn("0 with something to convert", out.getvalue())

    def test_trip_or_all_not_both(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command("convert_day_first", "--all", "--trip", str(self.trip.pk), stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("convert_day_first", stdout=StringIO())


class NoteTests(Fixture):
    def test_the_page_shows_notes_like_what_they_replace(self):
        day_first.apply(self.trip)
        self.client.force_login(self.viewer)
        html = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        self.assertIn('callout callout-info"><span class="font-semibold">Tip:</span> Pickup is in the terminal', html)
        self.assertIn("Morning — Arrive</h3>", html)
        self.assertIn("<p>• Coffee</p>", html)

    def test_the_form_round_trips_other_keys(self):
        form = NotePayloadForm({"tone": "warning", "paragraphs": "One\n\nTwo"}, content={"source": "docx"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.to_content(), {"source": "docx", "tone": "warning", "paragraphs": ["One", "Two"]})

    def test_tidy_reads_notes_as_what_they_replaced(self):
        """A converted "Book …" callout and an empty "19:30 — Dinner" phase still get their suggestions."""
        from apps.trips.models import BookingTask
        Section.objects.all().delete()
        Section.objects.create(day=self.day, section_type="callout", title="Book", order=1,
                               content={"tone": "critical", "text": "Book the Augustiner table"})
        Section.objects.create(day=self.day, section_type="phase", title="19:30 — Dinner", order=2,
                               content={"heading": "19:30 — Dinner"})
        Meal.objects.create(day=self.day, name="Augustiner", meal_type="dinner")
        BookingTask.objects.create(trip=self.trip, title="Book the Augustiner table")
        before = sorted(s.kind for s in tidying.suggestions(self.trip))
        day_first.apply(self.trip)
        found = tidying.suggestions(self.trip)
        self.assertEqual(sorted(s.kind for s in found), before)
        self.assertIn("meal_phase", before)
        applied, skipped = tidying.apply(self.trip, found, {s.key: s.actions[0][0] for s in found})
        self.assertEqual(skipped, [])
        self.assertEqual(Meal.objects.get().reserved_time, time(19, 30))
