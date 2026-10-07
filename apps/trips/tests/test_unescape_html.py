"""Tests for the ``unescape_html`` management command."""

from datetime import date
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.trips.models import Day, Section, Trip

User = get_user_model()


class UnescapeHtmlTests(TestCase):
    def setUp(self):
        self.trip = Trip.objects.create(
            name="James &amp; Regan &mdash; Taos",
            start_date="2026-09-12",
            end_date="2026-09-19",
            notes="AT&T and a < b and 5 &lt; 6 and a &hearts; b",
        )
        self.day = Day.objects.create(
            trip=self.trip,
            day_number=1,
            date=date(2026, 9, 12),
            theme="Arrival &amp; Santa Fe",
        )

    def run_command(self, *args):
        out, err = StringIO(), StringIO()
        call_command("unescape_html", *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_a_dry_run_reports_but_writes_nothing(self):
        out, err = self.run_command()

        self.trip.refresh_from_db()
        self.assertEqual(self.trip.name, "James &amp; Regan &mdash; Taos")
        self.assertIn("Would fix 3 value(s)", out)
        self.assertIn("James & Regan — Taos", out)
        self.assertIn("--apply", err)

    def test_apply_fixes_the_values(self):
        self.run_command("--apply")

        self.trip.refresh_from_db()
        self.day.refresh_from_db()
        self.assertEqual(self.trip.name, "James & Regan — Taos")
        self.assertEqual(self.day.theme, "Arrival & Santa Fe")

    def test_running_twice_changes_nothing_the_second_time(self):
        self.run_command("--apply")
        out, _err = self.run_command("--apply")

        self.trip.refresh_from_db()
        self.assertEqual(self.trip.name, "James & Regan — Taos")
        self.assertIn("Fixed 0 value(s)", out)

    def test_a_bare_ampersand_and_an_unlisted_entity_are_left_alone(self):
        # "AT&T" is not an entity and "a < b" is not one, so neither is
        # rewritten; &lt; is on the list and is resolved; &hearts; is not on
        # the list and is left exactly as typed.
        self.run_command("--apply")
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.notes, "AT&T and a < b and 5 < 6 and a &hearts; b")

    def test_numeric_entities_are_resolved(self):
        meal_note = Section.objects.create(
            day=self.day,
            section_type=Section.Type.CALLOUT,
            content={},
            title="Caf&#233; &amp; bar",
        )
        self.run_command("--apply")
        meal_note.refresh_from_db()
        self.assertEqual(meal_note.title, "Café & bar")

    def test_json_content_is_never_touched(self):
        section = Section.objects.create(
            day=self.day,
            section_type=Section.Type.FREE_TEXT,
            content={"paragraphs": ["Tom &amp; Jerry"]},
            title="fine",
        )
        self.run_command("--apply")
        section.refresh_from_db()
        self.assertEqual(section.content, {"paragraphs": ["Tom &amp; Jerry"]})

    def test_a_value_escaped_twice_is_reported_as_only_half_fixed(self):
        self.trip.name = "James &amp;amp; Regan"
        self.trip.save(update_fields=["name"])

        _out, err = self.run_command("--apply")
        self.trip.refresh_from_db()

        self.assertEqual(self.trip.name, "James &amp; Regan")
        self.assertIn("escaped more than once", err)
        self.assertIn("Run this again", err)

        # And the second run finishes it.
        _out, err = self.run_command("--apply")
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.name, "James & Regan")
        self.assertNotIn("escaped more than once", err)

    def test_an_unknown_table_prefix_is_an_error(self):
        with self.assertRaises(CommandError):
            self.run_command("--table-prefix", "nope_")

    def test_it_ignores_tables_outside_the_prefix(self):
        user = User.objects.create_user("zoe", "z@e.com", "pw-1234-abcd")
        user.first_name = "Tom &amp; Jerry"
        user.save()

        self.run_command("--apply")
        user.refresh_from_db()
        self.assertEqual(user.first_name, "Tom &amp; Jerry")

    def test_a_clean_database_reports_nothing(self):
        Trip.objects.all().delete()
        Day.objects.all().delete()
        out, err = self.run_command("--apply")
        self.assertIn("Fixed 0 value(s)", out)
        self.assertNotIn("dry run", err)