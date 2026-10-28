"""Decision to-dos turned into choices, merging into one the day already has
(docs/plans/retire-decision-todos.md, D1; apps/trips/day_first.py)."""
from datetime import date
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.trips import day_first
from apps.trips.models import (BookingTask, Day, Lodging, Option, OptionGroup, TaskOption, Trip, TripGrant,
                               TripRole)

User = get_user_model()


def group(prompt, *options):
    return SimpleNamespace(prompt=prompt, option_titles=list(options))


class MatchTests(SimpleTestCase):
    def test_a_shared_significant_word(self):
        found = group("Where to stay in Augsburg")
        self.assertIs(day_first.match_group("Augsburg hotel?", [], [found, group("Dinner")]), found)

    def test_stop_words_alone_dont_match(self):
        self.assertIsNone(day_first.match_group("Which hotel to book", [], [group("Where to stay")]))

    def test_capitals_and_accents(self):
        found = group("Lunch in München")
        self.assertIs(day_first.match_group("MUENCHEN lunch spot", [], [found]), found)

    def test_an_option_in_common(self):
        found = group("Tonight", "Hotel Augusta", "Drei Mohren")
        self.assertIs(day_first.match_group("Accommodation", ["Drei Mohren"], [found]), found)

    def test_two_matches_are_none(self):
        self.assertIsNone(day_first.match_group("Augsburg hotel", [], [group("Augsburg dinner"),
                                                                       group("Augsburg stay")]))
        self.assertEqual(len(day_first.matching_groups("Augsburg hotel", [], [group("Augsburg dinner"),
                                                                              group("Augsburg stay")])), 2)


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 20), end_date=date(2027, 9, 23),
                                        created_by=self.editor, home_currency="EUR")
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.day1 = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 20))
        self.day4 = Day.objects.create(trip=self.trip, day_number=4, date=date(2027, 9, 23))
        self.existing = OptionGroup.objects.create(trip=self.trip, day=self.day4, prompt="Where to stay in Augsburg")
        self.augusta = Option.objects.create(group=self.existing, title="Hotel Augusta", order=0)
        self.task = BookingTask.objects.create(trip=self.trip, title="Augsburg accommodation", kind="decide",
                                               day=self.day4, priority=1, notes="Ask about parking")
        TaskOption.objects.create(task=self.task, title="hotel augusta", order=0, chosen=True)
        TaskOption.objects.create(task=self.task, title="Drei Mohren", order=1, detail="Old town",
                                  est_cost=Decimal("210"), currency="EUR", url="https://example.com/m")

    def conversion(self):
        return next(c for _day, items in day_first.plan(self.trip) for c in items if c.source == self.task)


class PlanAndMergeTests(Fixture):
    def test_the_plan_matches_the_days_open_choice(self):
        conversion = self.conversion()
        self.assertEqual(conversion.target, self.existing)
        self.assertEqual(conversion.default_target, f"group-{self.existing.pk}")
        self.assertEqual(conversion.after[1][:3], ["Merge into “Where to stay in Augsburg” (Day 4)",
                                                   "• hotel augusta (already there)", "• Drei Mohren"])

    def test_never_matches_on_the_day_1_fallback(self):
        OptionGroup.objects.create(trip=self.trip, day=self.day1, prompt="Augsburg tour")
        self.task.day = None
        self.task.save()
        conversion = self.conversion()
        self.assertEqual((conversion.day, conversion.target), (self.day1, None))
        self.assertTrue(conversion.flag)

    def test_a_picked_choice_isnt_matched(self):
        self.existing.pick(self.augusta)
        self.assertIsNone(self.conversion().target)

    def test_merge_adds_only_missing_options_and_picks_the_chosen_one(self):
        self.assertEqual(day_first.apply(self.trip, user=self.editor), 1)
        self.assertEqual(self.trip.option_groups.count(), 1)  # no duplicate
        self.existing.refresh_from_db()
        self.assertEqual(list(self.existing.options.values_list("title", flat=True)), ["Hotel Augusta", "Drei Mohren"])
        mohren = self.existing.options.get(title="Drei Mohren")
        self.assertEqual((mohren.notes, mohren.est_cost, mohren.url, mohren.order), ("Old town", 210,
                                                                                    "https://example.com/m", 1))
        self.assertEqual((self.existing.state, self.existing.chosen_option(), self.existing.decided_by),
                         ("picked", self.augusta, self.editor))

    def test_merging_into_a_typed_stay_choice_makes_the_stay(self):
        self.existing.kind = OptionGroup.Kind.STAY
        self.existing.nights = 2
        self.existing.save()
        day_first.apply(self.trip)
        stay = Lodging.objects.get()
        self.assertEqual((stay.name, stay.check_in, stay.option), ("Hotel Augusta", self.day4.date, self.augusta))

    def test_a_chosen_option_on_a_decided_group_becomes_a_note(self):
        """``merge`` itself: an existing pick is kept and the to-do's choice is noted."""
        mohren = Option.objects.create(group=self.existing, title="Drei Mohren", order=1)
        self.existing.pick(mohren)
        day_first.merge(self.existing, [{"title": "Hotel Augusta", "notes": "", "url": "", "est_cost": None,
                                         "currency": "", "order": 0, "chosen": True}])
        self.existing.refresh_from_db()
        self.assertEqual(self.existing.chosen_option(), mohren)
        self.assertIn("Earlier choice: Hotel Augusta", self.existing.notes)

    def test_the_todo_stays_open_as_the_booking_todo(self):
        day_first.apply(self.trip)
        self.task.refresh_from_db()
        self.assertEqual((self.task.kind, self.task.done, self.task.priority), ("book", False, 1))
        self.assertEqual(self.task.notes, "Ask about parking\nOptions moved to the choice “Where to stay in "
                                          "Augsburg” on Day 4.")
        self.assertFalse(TaskOption.objects.exists())
        self.assertEqual(day_first.plan(self.trip), [])
        self.assertEqual(day_first.pending_count(self.trip), 0)

    def test_tick_it_off_instead(self):
        day_first.apply(self.trip, tick_off=True)
        self.task.refresh_from_db()
        self.assertTrue(self.task.done)

    def test_new_choice_when_asked(self):
        key = f"task-{self.task.pk}"
        day_first.apply(self.trip, [key], {key: "new"})
        made = self.trip.option_groups.exclude(pk=self.existing.pk).get()
        self.assertEqual((made.prompt, made.day, made.state), ("Augsburg accommodation", self.day4, "picked"))
        self.assertEqual(self.existing.options.count(), 1)

    def test_ambiguous_is_skipped_until_one_is_picked(self):
        other = OptionGroup.objects.create(trip=self.trip, day=self.day4, prompt="Augsburg dinner")
        conversion = self.conversion()
        self.assertEqual((conversion.target, conversion.default_target), (None, ""))
        self.assertEqual(set(conversion.ambiguous), {self.existing, other})
        self.assertEqual(day_first.apply(self.trip), 0)
        key = f"task-{self.task.pk}"
        self.assertEqual(day_first.apply(self.trip, [key], {key: ""}), 0)
        self.assertEqual(day_first.apply(self.trip, [key], {key: f"group-{self.existing.pk}"}), 1)
        self.assertEqual(self.existing.options.count(), 2)

    def test_another_days_group_is_refused(self):
        far = OptionGroup.objects.create(trip=self.trip, day=self.day1, prompt="Elsewhere")
        key = f"task-{self.task.pk}"
        self.assertEqual(day_first.apply(self.trip, [key], {key: f"group-{far.pk}"}), 0)


class PageTests(Fixture):
    def url(self, **query):
        from urllib.parse import urlencode
        return reverse("trips:trip_convert", args=[self.trip.pk]) + (f"?{urlencode(query)}" if query else "")

    def test_rows_say_merge_or_new_with_a_select_and_tick_off(self):
        BookingTask.objects.create(trip=self.trip, title="Bike or boat", kind="decide", day=self.day1
                                   ).options.create(title="Bike")
        self.client.force_login(self.editor)
        html = self.client.get(self.url()).content.decode()
        self.assertEqual(html.count("data-convert-row"), 2)
        self.assertIn(f'<option value="group-{self.existing.pk}" selected>Merge into “Where to stay in Augsburg” '
                      f'(Day 4)</option>', html)
        self.assertIn('<option value="new" selected>New choice on Day 1</option>', html)
        self.assertIn(f'name="tick-task-{self.task.pk}"', html)

    def test_one_todo_and_back(self):
        BookingTask.objects.create(trip=self.trip, title="Bike or boat", kind="decide", day=self.day1
                                   ).options.create(title="Bike")
        self.client.force_login(self.editor)
        todo = reverse("trips:trip_todo", args=[self.trip.pk])
        html = self.client.get(self.url(task=self.task.pk, next=todo)).content.decode()
        self.assertEqual(html.count("data-convert-row"), 1)
        key = f"task-{self.task.pk}"
        response = self.client.post(self.url(), {"task": self.task.pk, "next": todo, "item": key,
                                                 f"target-{key}": "new", f"tick-{key}": "1"})
        self.assertRedirects(response, todo, fetch_redirect_response=False)
        self.task.refresh_from_db()
        self.assertTrue(self.task.done)
        self.assertEqual(self.trip.option_groups.count(), 2)
        self.assertEqual(BookingTask.objects.get(title="Bike or boat").options.count(), 1)  # untouched

    def test_editors_only(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_make_it_a_choice_on_the_trip_page_and_todo_page(self):
        self.client.force_login(self.editor)
        link = self.url(task=self.task.pk)
        for name in ("trip_detail", "trip_todo"):
            self.assertContains(self.client.get(reverse(f"trips:{name}", args=[self.trip.pk])), link)


class CommandTests(Fixture):
    def test_dry_run_says_merge_or_new_and_skips_ambiguous(self):
        loose = BookingTask.objects.create(trip=self.trip, title="Bike or boat", kind="decide", day=self.day1)
        loose.options.create(title="Bike")
        out = StringIO()
        call_command("convert_day_first", trip=self.trip.pk, stdout=out)
        text = out.getvalue()
        self.assertIn("→  Merge into “Where to stay in Augsburg” (Day 4)", text)
        self.assertIn("→  New choice on Day 1: Bike or boat (undecided)", text)
        self.assertIn("Dry run", text)
        self.assertEqual(self.existing.options.count(), 1)
        OptionGroup.objects.create(trip=self.trip, day=self.day4, prompt="Augsburg dinner")
        out = StringIO()
        call_command("convert_day_first", "--trip", str(self.trip.pk), "--apply", "--tick-off", stdout=out)
        self.assertIn("left as it is: looks like", out.getvalue())
        self.assertIn("Converted 1.", out.getvalue())
        loose.refresh_from_db()
        self.task.refresh_from_db()
        self.assertEqual((loose.done, self.task.kind), (True, "decide"))  # the ambiguous one waits
