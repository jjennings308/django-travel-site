"""The retired section types as notes and groups, and decision to-dos turned into choices
(docs/plans/day-first-planning.md P3–P4; docs/plans/retire-old-section-types.md S1–S2)."""
from datetime import date, time

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase
from django.urls import reverse

from apps.core.testing import RestoringTransactionTestCase
from apps.trips import changes, day_first, tidying
from apps.trips.forms import NotePayloadForm
from apps.trips.models import (BookingTask, Day, Meal, Section, Trip, TripChange, TripGrant,
                               TripRole)

User = get_user_model()

PHASE = {"heading": "Morning — Arrive", "summary": "Land FRA.", "highlights": ["Coffee", "Nap"], "source": "docx"}
CALLOUT = {"tone": "info", "text": "Pickup is in the terminal"}
FREE_TEXT = {"paragraphs": ["First.", "Second."]}


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Alps", start_date=date(2027, 9, 18), end_date=date(2027, 9, 21),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 18))


class MappingTests(TestCase):
    """The one mapping the importer and history restore share (the migration keeps a frozen copy)."""

    def test_a_phase_callout_and_free_text_as_notes(self):
        self.assertEqual(day_first.note_from("phase", "Arrive", PHASE),
                         ("Morning — Arrive", {"tone": "", "paragraphs": ["Land FRA.", "• Coffee", "• Nap"],
                                               "source": "docx"}))
        self.assertEqual(day_first.note_from("callout", "Tip", CALLOUT),
                         ("Tip", {"tone": "tip", "paragraphs": ["Pickup is in the terminal"]}))
        self.assertEqual(day_first.note_from("free_text", "Notes", FREE_TEXT),
                         ("Notes", {"tone": "", "paragraphs": ["First.", "Second."]}))
        self.assertEqual(day_first.note_from("callout", "", {"tone": "warning", "text": "One\n\nTwo"})[1],
                         {"tone": "warning", "paragraphs": ["One", "Two"]})
        self.assertEqual(day_first.note_from("phase", "", "not a dict"), ("", {"tone": "", "paragraphs": []}))

    def test_the_payload_is_not_changed_in_place(self):
        stored = dict(PHASE)
        day_first.note_from("phase", "Arrive", stored)
        self.assertEqual(stored, PHASE)

    def test_as_note_handles_every_retired_type(self):
        self.assertEqual(day_first.as_note("choose_your_adventure", "T", {"prompt": "P", "options": [{"title": "A"}]}),
                         ("P", {"tone": "", "paragraphs": ["• A"]}))
        self.assertEqual(day_first.as_note("free_text", "N", FREE_TEXT)[0], "N")


class ImportTests(Fixture):
    def test_the_importer_saves_notes_and_groups(self):
        """``import_itinerary`` never saves a retired type: what the parser calls a phase, callout or free text
        is saved as a note, a choose-your-adventure as a "choose one" group."""
        from apps.trips.management.commands.import_itinerary import Command
        command = Command()
        for order, (kind, title, content) in enumerate((("phase", "Arrive", PHASE), ("callout", "Tip", CALLOUT),
                                                       ("free_text", "Notes", FREE_TEXT),
                                                       ("logistics_table", "Trains", {"columns": ["Leg"], "rows": []}),
                                                       ("choose_your_adventure", "Afternoon",
                                                        {"prompt": "Lake or town?", "options": [{"title": "Lake"},
                                                                                                {"title": "Town"}]}))):
            command._save_section(self.trip, self.day, {"section_type": kind, "title": title, "icon": "",
                                                        "order": order, "content": content})
        self.assertEqual(list(Section.objects.order_by("order").values_list("section_type", "title")),
                         [("note", "Morning — Arrive"), ("note", "Tip"), ("note", "Notes"),
                          ("logistics_table", "Trains")])
        group = self.trip.option_groups.get()
        self.assertEqual((group.prompt, group.order, [o.title for o in group.options.all()]),
                         ("Lake or town?", 4, ["Lake", "Town"]))


class RestoreTests(Fixture):
    def removed(self, **fields):
        """A removed section's history line, its snapshot changed to look like one taken before S2."""
        section = Section.objects.create(day=self.day, section_type="note", title="x", order=2)
        section.delete()
        change = TripChange.objects.filter(kind=TripChange.Kind.REMOVED).latest("pk")
        change.before["object"]["fields"].update(fields)
        change.save(update_fields=["before"])
        return change

    def test_an_old_snapshot_comes_back_as_a_note(self):
        change = self.removed(section_type="phase", title="Arrive", content=PHASE)
        restored = changes.restore(change, self.editor)
        restored.refresh_from_db()
        self.assertEqual((restored.section_type, restored.title, restored.order), ("note", "Morning — Arrive", 2))
        self.assertEqual(restored.content["paragraphs"], ["Land FRA.", "• Coffee", "• Nap"])

    def test_an_old_choose_your_adventure_snapshot_comes_back_as_a_note(self):
        change = self.removed(section_type="choose_your_adventure", title="Afternoon",
                              content={"prompt": "Pick", "options": [{"title": "Lake"}]})
        restored = changes.restore(change, self.editor)
        self.assertEqual((restored.section_type, restored.title, restored.content["paragraphs"]),
                         ("note", "Pick", ["• Lake"]))




class NoteTests(Fixture):
    def test_the_page_draws_notes(self):
        Section.objects.create(day=self.day, section_type="note", title="Tip", order=1,
                               content={"tone": "tip", "paragraphs": ["Pickup is in the terminal"]})
        Section.objects.create(day=self.day, section_type="note", title="Morning — Arrive", order=2,
                               content={"tone": "", "paragraphs": ["• Coffee"]})
        self.client.force_login(self.viewer)
        html = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        self.assertIn('callout callout-info"><span class="font-semibold">Tip:</span> Pickup is in the terminal', html)
        self.assertIn("Morning — Arrive</h3>", html)
        self.assertIn("<p>• Coffee</p>", html)

    def test_the_form_round_trips_other_keys(self):
        form = NotePayloadForm({"tone": "warning", "paragraphs": "One\n\nTwo"}, content={"source": "docx"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.to_content(), {"source": "docx", "tone": "warning", "paragraphs": ["One", "Two"]})

    def test_tidy_reads_notes_as_callouts_and_phases(self):
        """A toned one-paragraph "Book …" note and an empty "19:30 — Dinner" note get the suggestions a callout and
        a phase used to."""
        Section.objects.create(day=self.day, section_type="note", title="Book", order=1,
                               content={"tone": "critical", "paragraphs": ["Book the Augustiner table"]})
        Section.objects.create(day=self.day, section_type="note", title="19:30 — Dinner", order=2,
                               content={"tone": "", "paragraphs": []})
        Meal.objects.create(day=self.day, name="Augustiner", meal_type="dinner")
        BookingTask.objects.create(trip=self.trip, title="Book the Augustiner table")
        found = tidying.suggestions(self.trip)
        self.assertEqual(sorted(s.kind for s in found), ["callout_task", "meal_phase"])
        applied, skipped = tidying.apply(self.trip, found, {s.key: s.actions[0][0] for s in found})
        self.assertEqual(skipped, [])
        self.assertEqual(Meal.objects.get().reserved_time, time(19, 30))
        self.assertFalse(Section.objects.exists())


class RetireMigrationTests(RestoringTransactionTestCase):
    """trips 0051: phases, callouts and free text left become notes; a leftover choose-your-adventure stops it."""

    BEFORE = [("trips", "0050_trip_ideas")]
    AFTER = [("trips", "0051_retire_old_section_types")]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        pinned = dict(targets)
        nodes = [(app, pinned.get(app, name)) for app, name in executor.loader.graph.leaf_nodes()]
        executor.migrate(nodes)
        executor.loader.build_graph()
        return executor.loader.project_state(nodes).apps

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def day(self, apps):
        Trip = apps.get_model("trips", "Trip")
        Day = apps.get_model("trips", "Day")
        trip = Trip.objects.create(name="Old trip", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        return Day.objects.create(trip=trip, day_number=1, date=date(2027, 1, 1))

    def test_old_note_types_become_notes(self):
        apps = self.migrate(self.BEFORE)
        Section = apps.get_model("trips", "Section")
        day = self.day(apps)
        olds = (("phase", "Arrive", PHASE), ("callout", "Tip", CALLOUT), ("free_text", "Notes", FREE_TEXT))
        made = [(Section.objects.create(day=day, section_type=kind, title=title, content=content, order=n).pk,
                 kind, title, content) for n, (kind, title, content) in enumerate(olds)]
        table = Section.objects.create(day=day, section_type="logistics_table", content={"rows": []}).pk
        apps = self.migrate(self.AFTER)
        Section = apps.get_model("trips", "Section")
        for pk, kind, title, content in made:
            row = Section.objects.get(pk=pk)
            self.assertEqual((row.section_type, row.title, row.content),
                             ("note", *day_first.note_from(kind, title, content)), kind)
        self.assertEqual(Section.objects.get(pk=table).section_type, "logistics_table")

    def test_a_leftover_choose_your_adventure_stops_it(self):
        apps = self.migrate(self.BEFORE)
        Section = apps.get_model("trips", "Section")
        day = self.day(apps)
        Section.objects.create(day=day, section_type="choose_your_adventure", content={"options": []})
        with self.assertRaisesMessage(RuntimeError, "run `manage.py convert_day_first --all --apply` first"):
            self.migrate(self.AFTER)
        Section.objects.filter(section_type="choose_your_adventure").delete()
