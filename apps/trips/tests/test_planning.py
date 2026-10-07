"""Tests for trip planning: ``Trip.status`` and ``BookingTask``.

Covers the parts that are easy to get quietly wrong: the outstanding count
preferring an annotation over a per-object query, ``SET_NULL`` on the optional
links so tidying a day never destroys the task behind it, and the import
command's ``--status`` precedence — particularly inheriting the status on
``--replace``, which is the case that would otherwise silently reset a finished
trip back to "starting" every time the parser was fixed.
"""

import importlib
import io
import tempfile
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.models import Count, Q
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext

from apps.trips.admin import (
    DayAdmin,
    RosterFilter,
    TransportLegAdmin,
    TripAdmin,
)
from apps.trips.forms import DayAdminForm, TransportLegAdminForm
from apps.trips.models import (
    BookingTask,
    Confirmation,
    Day,
    Traveler,
    TransportLeg,
    Trip,
)
from apps.trips.tests.test_docx_import import build_document, run_import

User = get_user_model()


def make_trip(**kwargs):
    defaults = {
        "name": "Test Trip",
        "start_date": date(2026, 9, 12),
        "end_date": date(2026, 9, 19),
    }
    defaults.update(kwargs)
    return Trip.objects.create(**defaults)


class TripStatusTests(TestCase):
    def test_default_status_is_starting(self):
        self.assertEqual(make_trip().status, Trip.Status.STARTING)

    def test_is_ready_only_for_ready_to_go(self):
        trip = make_trip()
        for status in (
            Trip.Status.STARTING,
            Trip.Status.FLESHING_OUT,
            Trip.Status.CONFIRMING,
        ):
            trip.status = status
            self.assertFalse(trip.is_ready, status)
        trip.status = Trip.Status.READY_TO_GO
        self.assertTrue(trip.is_ready)

    def test_str_is_the_bare_name(self):
        trip = make_trip(name="James & Regan — Taos / Angel Fire, New Mexico")
        self.assertEqual(str(trip), "James & Regan — Taos / Angel Fire, New Mexico")

    def test_is_ready_is_false_with_no_tasks_at_all(self):
        # A finished trip is defined by having nothing outstanding, not by
        # having marked things done.
        self.assertTrue(make_trip(status=Trip.Status.READY_TO_GO).is_ready)


class OutstandingTaskCountTests(TestCase):
    def setUp(self):
        self.trip = make_trip()
        self.other = make_trip(name="Other Trip")

    def test_counts_only_undone_tasks(self):
        BookingTask.objects.create(trip=self.trip, title="a", done=False)
        BookingTask.objects.create(trip=self.trip, title="b", done=False)
        BookingTask.objects.create(trip=self.trip, title="c", done=True)
        self.assertEqual(self.trip.outstanding_booking_tasks, 2)

    def test_excludes_other_trips_tasks(self):
        BookingTask.objects.create(trip=self.other, title="theirs", done=False)
        self.assertEqual(self.trip.outstanding_booking_tasks, 0)

    def test_unsaved_trip_reports_zero_without_querying(self):
        # The property is reachable from admin forms, where a trip may not
        # exist yet; it must not explode on a missing pk.
        with self.assertNumQueries(0):
            self.assertEqual(Trip(name="Draft").outstanding_booking_tasks, 0)

    def test_prefers_annotation_over_a_query(self):
        BookingTask.objects.create(trip=self.trip, title="a", done=False)
        annotated = (
            Trip.objects.filter(pk=self.trip.pk)
            .annotate(
                outstanding_task_count=Count(
                    "booking_tasks", filter=Q(booking_tasks__done=False)
                )
            )
            .get()
        )
        with self.assertNumQueries(0):
            self.assertEqual(annotated.outstanding_booking_tasks, 1)


class BookingTaskModelTests(TestCase):
    def setUp(self):
        self.trip = make_trip()
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2026, 9, 12))
        self.confirmation = Confirmation.objects.create(
            trip=self.trip, label="Hotel", confirmation_number="ABC123"
        )

    def test_default_priority_is_medium(self):
        task = BookingTask.objects.create(trip=self.trip, title="Book the flights")
        self.assertEqual(task.priority, BookingTask.Priority.MEDIUM)

    def test_due_and_links_are_optional(self):
        task = BookingTask.objects.create(trip=self.trip, title="Trip-only task")
        self.assertIsNone(task.day)
        self.assertIsNone(task.confirmation)
        self.assertIsNone(task.due)

    def test_outstanding_tasks_sort_before_done_ones(self):
        BookingTask.objects.create(trip=self.trip, title="done", done=True)
        BookingTask.objects.create(
            trip=self.trip, title="open", priority=BookingTask.Priority.LOW
        )
        titles = list(
            BookingTask.objects.filter(trip=self.trip).values_list("title", flat=True)
        )
        self.assertEqual(titles, ["open", "done"])

    def test_sorting_within_priority_follows_order_then_id(self):
        first = BookingTask.objects.create(trip=self.trip, title="b", order=2)
        second = BookingTask.objects.create(trip=self.trip, title="a", order=1)
        BookingTask.objects.create(trip=self.trip, title="later", order=9)
        titles = list(
            BookingTask.objects.filter(trip=self.trip).values_list("title", flat=True)
        )
        self.assertEqual(titles, ["a", "b", "later"])
        self.assertEqual([first.order, second.order], [2, 1])

    def test_deleting_a_day_keeps_the_task(self):
        task = BookingTask.objects.create(trip=self.trip, title="x", day=self.day)
        self.day.delete()
        task.refresh_from_db()
        self.assertIsNone(task.day)
        self.assertEqual(task.title, "x")

    def test_deleting_a_confirmation_keeps_the_task(self):
        task = BookingTask.objects.create(
            trip=self.trip, title="y", confirmation=self.confirmation
        )
        self.confirmation.delete()
        task.refresh_from_db()
        self.assertIsNone(task.confirmation)

    def test_deleting_the_trip_removes_the_tasks(self):
        BookingTask.objects.create(trip=self.trip, title="z")
        self.trip.delete()
        self.assertEqual(BookingTask.objects.count(), 0)

    def test_task_can_link_a_day_and_a_confirmation(self):
        task = BookingTask.objects.create(
            trip=self.trip,
            title="Confirm pickup window",
            day=self.day,
            confirmation=self.confirmation,
        )
        self.assertEqual(task.day_id, self.day.pk)
        self.assertEqual(task.confirmation_id, self.confirmation.pk)


class StatusDataMigrationTests(TestCase):
    """The 0004 data migration keys on name and dates, not on pk.

    pk differs between this machine and the production box, so a migration
    keyed on it would silently mark nothing on one of the two.
    """

    def setUp(self):
        module = importlib.import_module(
            "apps.trips.migrations.0004_mark_booked_trip_ready_to_go"
        )
        self.module = module
        self.apps = type(
            "_Apps", (), {"get_model": staticmethod(lambda *a, **k: Trip)}
        )()

    def test_marks_the_matching_trip(self):
        make_trip(
            name=(
                "James & Regan \u2014 Taos / Angel Fire, "
                "New Mexico"
            ),
            start_date=date(2026, 9, 12),
            end_date=date(2026, 9, 19),
        )
        self.module.mark_ready(self.apps, None)
        self.assertEqual(Trip.objects.get().status, Trip.Status.READY_TO_GO)

    def test_leaves_other_trips_alone(self):
        make_trip(name="Europe 2027", start_date=date(2027, 9, 18), end_date=date(2027, 10, 3))
        self.module.mark_ready(self.apps, None)
        self.assertEqual(Trip.objects.get().status, Trip.Status.STARTING)

    def test_requires_the_dates_to_match_too(self):
        make_trip(
            name="James & Regan \u2014 Taos / Angel Fire, New Mexico",
            start_date=date(2026, 9, 12),
            end_date=date(2026, 9, 20),
        )
        self.module.mark_ready(self.apps, None)
        self.assertEqual(Trip.objects.get().status, Trip.Status.STARTING)

    def test_reverse_returns_to_the_default(self):
        make_trip(
            name="James & Regan \u2014 Taos / Angel Fire, New Mexico",
            start_date=date(2026, 9, 12),
            end_date=date(2026, 9, 19),
        )
        self.module.mark_ready(self.apps, None)
        self.module.unmark_ready(self.apps, None)
        self.assertEqual(Trip.objects.get().status, Trip.Status.STARTING)


class ImportStatusFlagTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = build_document(self._tmp.name)

    def test_defaults_to_starting(self):
        run_import(self.path, apply=True)
        self.assertEqual(Trip.objects.get().status, Trip.Status.STARTING)

    def test_explicit_status_is_saved(self):
        run_import(self.path, apply=True, status=Trip.Status.CONFIRMING)
        self.assertEqual(Trip.objects.get().status, Trip.Status.CONFIRMING)

    def test_dry_run_reports_the_status_it_would_save(self):
        out = io.StringIO()
        with redirect_stdout(out):
            call_command(
                "import_itinerary",
                str(self.path),
                status=Trip.Status.FLESHING_OUT,
            )
        self.assertIn("fleshing_out", out.getvalue())
        self.assertIn("from --status", out.getvalue())
        self.assertEqual(Trip.objects.count(), 0)

    def test_replace_inherits_the_previous_status(self):
        run_import(self.path, apply=True, status=Trip.Status.READY_TO_GO)
        run_import(self.path, apply=True, replace=True)
        self.assertEqual(Trip.objects.get().status, Trip.Status.READY_TO_GO)

    def test_explicit_status_overrides_on_replace(self):
        run_import(self.path, apply=True, status=Trip.Status.READY_TO_GO)
        run_import(self.path, apply=True, replace=True, status=Trip.Status.STARTING)
        self.assertEqual(Trip.objects.get().status, Trip.Status.STARTING)

    def test_dry_run_does_not_inherit_without_replace(self):
        run_import(self.path, apply=True, status=Trip.Status.READY_TO_GO)
        out = io.StringIO()
        with redirect_stdout(out):
            call_command("import_itinerary", str(self.path))
        self.assertIn("default", out.getvalue())

    def test_unknown_status_is_rejected(self):
        with self.assertRaises(CommandError):
            run_import(self.path, apply=True, status="nonsense")


class TripAdminTests(TestCase):
    """Covers the trip-side admin behaviour added with ``Trip.status``.

    The warning tests go through a real POST to the change form rather than
    calling a hook directly, because the hook choice is the bug they guard: a
    count taken in ``save_model`` runs before ``save_related`` and misses
    booking tasks submitted by the inline in the same request. These trips have
    no days, flights or lodging, so the POST is a fixed set of empty management
    forms plus the checklist — no HTML scraping needed.
    """

    def setUp(self):
        self.user = User.objects.create_superuser(
            "admin", "admin@example.com", "password"
        )
        self.client.force_login(self.user)
        self.admin = TripAdmin(Trip, AdminSite())
        self.trip = make_trip(name="Test Trip")

    def _post(self, status, tasks=()):
        """Save the trip via the admin, adding `tasks` to the checklist.

        Each task is a ``(title, priority, done)`` triple so a test can add a
        completed task in the same request as marking the trip ready.
        """
        url = f"/admin/trips/trip/{self.trip.pk}/change/"
        data = {
            "name": self.trip.name,
            "destination": self.trip.destination,
            "start_date": str(self.trip.start_date),
            "end_date": str(self.trip.end_date),
            "status": status,
            "notes": self.trip.notes,
            "travelers": [],
            "_save": "Save",
        }
        # Every inline needs a management form; these trips have no rows in any
        # of the non-task inlines, so zero everywhere is valid and keeps the
        # payload independent of the admin's `extra` settings. The `transport`
        # prefix follows the related_name on TransportLeg.trip, and `grants`
        # the one on TripGrant.
        for prefix in ("days", "transport", "lodging", "confirmations", "contacts", "grants"):
            data[f"{prefix}-TOTAL_FORMS"] = "0"
            data[f"{prefix}-INITIAL_FORMS"] = "0"
        data["booking_tasks-TOTAL_FORMS"] = str(len(tasks))
        data["booking_tasks-INITIAL_FORMS"] = "0"
        data["booking_tasks-MIN_NUM_FORMS"] = "0"
        data["booking_tasks-MAX_NUM_FORMS"] = "1000"
        for i, (title, priority, done) in enumerate(tasks):
            data[f"booking_tasks-{i}-title"] = title
            data[f"booking_tasks-{i}-priority"] = str(priority)
            data[f"booking_tasks-{i}-order"] = "0"
            if done:
                data[f"booking_tasks-{i}-done"] = "on"
        return self.client.post(url, data, follow=True)

    def test_warns_when_ready_with_outstanding_tasks(self):
        response = self._post(
            Trip.Status.READY_TO_GO, [("Book flights", BookingTask.Priority.MEDIUM, False)]
        )
        self.assertContains(response, "1 outstanding booking task")

    def test_counts_a_task_added_in_the_same_request(self):
        # The regression this hook placement exists for: the task is created by
        # this very POST, so a count taken before save_related would see none.
        response = self._post(
            Trip.Status.READY_TO_GO, [("Book flights", BookingTask.Priority.MEDIUM, False)]
        )
        self.assertEqual(BookingTask.objects.count(), 1)
        self.assertContains(response, "1 outstanding booking task")

    def test_pluralises_the_warning(self):
        response = self._post(
            Trip.Status.READY_TO_GO,
            [
                ("a", BookingTask.Priority.MEDIUM, False),
                ("b", BookingTask.Priority.LOW, False),
            ],
        )
        self.assertContains(response, "2 outstanding booking tasks")

    def test_no_warning_when_the_new_task_is_ticked_off(self):
        response = self._post(
            Trip.Status.READY_TO_GO, [("Already done", BookingTask.Priority.MEDIUM, True)]
        )
        self.assertTrue(BookingTask.objects.get().done)
        self.assertNotContains(response, "outstanding booking task")

    def test_no_warning_when_nothing_outstanding(self):
        BookingTask.objects.create(trip=self.trip, title="Book flights", done=True)
        response = self._post(Trip.Status.READY_TO_GO)
        self.assertNotContains(response, "outstanding booking task")

    def test_no_warning_for_other_statuses(self):
        BookingTask.objects.create(trip=self.trip, title="Book flights", done=False)
        response = self._post(Trip.Status.CONFIRMING)
        self.assertNotContains(response, "outstanding booking task")

    def test_status_is_actually_saved(self):
        self._post(Trip.Status.FLESHING_OUT)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.status, Trip.Status.FLESHING_OUT)

    def test_changelist_annotates_and_shows_the_count(self):
        BookingTask.objects.create(trip=self.trip, title="Book flights", done=False)
        request = RequestFactory().get("/admin/trips/trip/")
        request.user = self.user
        rows = list(self.admin.get_queryset(request))
        self.assertEqual(rows[0].outstanding_booking_tasks, 1)

    def test_changelist_does_not_query_per_row(self):
        # Drop the setUp trip so the row count is unambiguous.
        self.trip.delete()
        for i in range(4):
            trip = make_trip(name=f"Trip {i}")
            BookingTask.objects.create(trip=trip, title="task", done=False)
        request = RequestFactory().get("/admin/trips/trip/")
        request.user = self.user
        queryset = self.admin.get_queryset(request)
        # One annotated SELECT for the whole page, not one COUNT per row.
        # Without the annotation this would be 1 + 4 queries.
        with self.assertNumQueries(1):
            self.assertEqual([row.outstanding_booking_tasks for row in queryset], [1] * 4)

    def test_status_is_listed_and_filterable(self):
        self.assertIn("status", self.admin.list_display)
        self.assertIn("status", self.admin.list_filter)

    def test_booking_task_inline_is_registered(self):
        from apps.trips.admin import BookingTaskInline

        self.assertIn(BookingTaskInline, self.admin.inlines)


class BookingTaskAdminTests(TestCase):
    def setUp(self):
        self.trip = make_trip()

    def _admin(self):
        from apps.trips.admin import BookingTaskAdmin

        return BookingTaskAdmin(BookingTask, AdminSite())

    def test_done_and_priority_are_editable_in_the_list(self):
        admin = self._admin()
        self.assertEqual(set(admin.list_editable), {"done", "priority"})

    def test_first_list_column_is_not_editable(self):
        # Django refuses to load a ModelAdmin whose first list_display field is
        # editable, because that column carries the link to the change page.
        admin = self._admin()
        self.assertNotIn(admin.list_display[0], admin.list_editable)

    def test_autocomplete_targets_are_searchable(self):
        # autocomplete_fields silently 500s unless the target admin has
        # search_fields.
        admin = self._admin()
        for field in admin.autocomplete_fields:
            target = {
                "trip": Trip,
                "day": Day,
                "confirmation": Confirmation,
            }[field]
            from apps.trips import admin as trips_admin

            self.assertTrue(getattr(trips_admin, f"{target.__name__}Admin").search_fields)


class DayRosterTests(TestCase):
    """``Day.travelers`` is blank for the common case; blank means everyone.

    The whole point is that a trip where nobody splits up needs no per-day
    data at all, so the interesting assertions are about what a blank roster
    resolves to, not about the field existing.
    """

    def setUp(self):
        self.trip = make_trip()
        self.ada = Traveler.objects.create(name="Ada")
        self.bo = Traveler.objects.create(name="Bo")
        self.trip.travelers.set([self.ada, self.bo])
        self.day = Day.objects.create(
            trip=self.trip, day_number=1, date=date(2026, 9, 12)
        )
        User.objects.create_superuser("roster-admin", "ro@example.com", "pw")

    def test_blank_roster_is_not_split(self):
        self.assertFalse(self.day.is_split)

    def test_blank_roster_resolves_to_the_whole_trip(self):
        self.assertEqual(
            sorted(t.name for t in self.day.roster), ["Ada", "Bo"]
        )

    def test_blank_roster_summary_says_whole_trip(self):
        self.assertEqual(self.day.roster_summary, "Whole trip")

    def test_named_roster_is_split(self):
        self.day.travelers.set([self.ada])
        self.assertTrue(self.day.is_split)

    def test_named_roster_narrows_to_those_people(self):
        self.day.travelers.set([self.ada])
        self.assertEqual([t.name for t in self.day.roster], ["Ada"])

    def test_roster_summary_lists_the_named_people(self):
        self.day.travelers.set([self.bo, self.ada])
        # Traveler has no Meta.ordering, so this follows insertion order.
        self.assertEqual(self.day.roster_summary, "Ada, Bo")

    def test_is_split_is_false_for_an_unsaved_day(self):
        # Reachable from an admin add form, where the row has no pk yet.
        draft = Day(trip=self.trip, day_number=2, date=date(2026, 9, 13))
        self.assertFalse(draft.is_split)
        with self.assertNumQueries(0):
            self.assertEqual(draft.roster_summary, "Whole trip")

    def test_roster_is_empty_when_the_trip_has_no_travelers(self):
        lonely = make_trip(name="No Crew")
        day = Day.objects.create(
            trip=lonely, day_number=1, date=date(2026, 9, 12)
        )
        self.assertEqual(list(day.roster), [])

    def _changelist_summaries(self):
        request = RequestFactory().get("/admin/trips/day/")
        request.user = User.objects.get(username="roster-admin")
        queryset = DayAdmin(Day, AdminSite()).get_queryset(request)
        return [row.roster_summary for row in queryset]

    def test_changelist_summary_does_not_query_per_row(self):
        self.day.travelers.set([self.ada])
        with CaptureQueriesContext(connection) as one_day:
            self._changelist_summaries()
        for i in range(2, 6):
            Day.objects.create(
                trip=self.trip, day_number=i, date=date(2026, 9, 11 + i)
            )
        with CaptureQueriesContext(connection) as five_days:
            summaries = self._changelist_summaries()
        # Same number of queries for five days as for one: the prefetch covers
        # the roster for every row, so this is a fixed cost, not an N+1.
        self.assertEqual(len(one_day), len(five_days))
        self.assertEqual(
            summaries, ["Ada", "Whole trip", "Whole trip", "Whole trip", "Whole trip"]
        )


class DayRosterFormTests(TestCase):
    """A day must not claim a traveler who is not on the trip."""

    def setUp(self):
        User.objects.create_superuser("roster-admin", "ro@example.com", "pw")
        self.trip = make_trip()
        self.on_trip = Traveler.objects.create(name="Ada")
        self.trip.travelers.set([self.on_trip])
        self.stranger = Traveler.objects.create(name="Mallory")
        self.day = Day.objects.create(
            trip=self.trip, day_number=1, date=date(2026, 9, 12)
        )

    def _form(self, **overrides):
        data = {
            "trip": self.trip.pk,
            "day_number": self.day.day_number,
            "date": str(self.day.date),
            "theme": "",
            "meals_included": "",
            "travelers": [],
        }
        data.update(overrides)
        return DayAdminForm(data=data, instance=self.day)

    def test_blank_roster_is_valid(self):
        self.assertTrue(self._form().is_valid())

    def test_roster_of_trip_travelers_is_valid(self):
        self.assertTrue(self._form(travelers=[self.on_trip.pk]).is_valid())

    def test_roster_naming_a_stranger_is_rejected(self):
        form = self._form(travelers=[self.on_trip.pk, self.stranger.pk])
        self.assertFalse(form.is_valid())
        self.assertIn("Mallory", str(form.errors))

    def test_error_explains_the_fix(self):
        form = self._form(travelers=[self.stranger.pk])
        form.is_valid()
        # Assert on a phrase without an apostrophe: form errors are rendered
        # escaped, so "trip's" arrives here as "trip&#x27;s".
        self.assertIn("or clear the field if the whole group is together", str(form.errors))


class RosterFilterTests(TestCase):
    def setUp(self):
        User.objects.create_superuser("roster-admin", "ro@example.com", "pw")
        self.trip = make_trip()
        self.ada = Traveler.objects.create(name="Ada")
        self.trip.travelers.set([self.ada])
        self.split = Day.objects.create(
            trip=self.trip, day_number=1, date=date(2026, 9, 12)
        )
        self.split.travelers.set([self.ada])
        self.whole = Day.objects.create(
            trip=self.trip, day_number=2, date=date(2026, 9, 13)
        )

    def _filtered(self, value):
        # SimpleListFilter expects each param as a *list* and reads value[-1]
        # (ChangeList._get_params normalises multi-valued GET params that way),
        # so passing a bare string silently yields only its last character.
        params = {"roster": [value]} if value is not None else {}
        request = RequestFactory().get("/admin/trips/day/", params)
        request.user = User.objects.get(username="roster-admin")
        filter_ = RosterFilter(request, params, Day, DayAdmin(Day, AdminSite()))
        self.assertEqual(filter_.value(), value)
        return filter_.queryset(request, Day.objects.all())

    def test_split_finds_only_narrowed_days(self):
        self.assertEqual(list(self._filtered("split")), [self.split])

    def test_whole_finds_only_untouched_days(self):
        self.assertEqual(list(self._filtered("whole")), [self.whole])

    def test_no_value_returns_everything(self):
        self.assertEqual(self._filtered(None).count(), 2)


class DayAdminWiringTests(TestCase):
    def setUp(self):
        self.admin = DayAdmin(Day, AdminSite())

    def test_roster_summary_is_a_list_column(self):
        self.assertIn("roster_summary", self.admin.list_display)

    def test_travelers_is_horizontally_filterable(self):
        self.assertIn("travelers", self.admin.filter_horizontal)

    def test_the_filter_is_registered(self):
        from apps.trips.admin import RosterFilter

        self.assertIn(RosterFilter, self.admin.list_filter)

    def test_changelist_prefetches_the_roster(self):
        qs = self.admin.get_queryset(RequestFactory().get("/admin/trips/day/"))
        self.assertIn("travelers", qs._prefetch_related_lookups)


class TransportLegModeTests(TestCase):
    """``TransportLeg`` is the old ``Flight`` model, taught modes beyond air.

    The rename exists because the Europe draft is train-heavy, so the point of
    this is not the model having a ``mode`` field — it is that a leg which is
    *not* a flight can be stored and rendered without inventing an operator.
    """

    def setUp(self):
        self.trip = make_trip()

    def _leg(self, **kwargs):
        # Real datetimes, not ISO strings: create() leaves the string it was
        # given in the in-memory instance, and localize() rejects anything
        # that is not a datetime.
        defaults = {
            "trip": self.trip,
            "origin": "ABQ",
            "destination": "DEN",
            "departure_at": datetime.fromisoformat("2026-09-12T14:00:00+00:00"),
            "arrival_at": datetime.fromisoformat("2026-09-12T15:00:00+00:00"),
        }
        defaults.update(kwargs)
        return TransportLeg.objects.create(**defaults)

    def test_mode_defaults_to_plane(self):
        self.assertEqual(self._leg().mode, TransportLeg.Mode.PLANE)

    def test_every_advertised_mode_round_trips(self):
        for value, _label in TransportLeg.Mode.choices:
            self.assertEqual(self._leg(mode=value).mode, value)

    def test_a_train_leg_carries_a_rail_operator_not_an_airline(self):
        # The point of the `operator` / `service_number` rename: a train has a
        # carrier and a service number, and neither of the old column names
        # described them.
        leg = self._leg(
            mode=TransportLeg.Mode.TRAIN,
            operator="Deutsche Bahn",
            service_number="ICE 1043",
            origin="Kitzbühel",
            destination="Innsbruck Hbf",
        )
        self.assertEqual(leg.mode, TransportLeg.Mode.TRAIN)
        self.assertEqual(leg.operator, "Deutsche Bahn")
        self.assertEqual(leg.service_number, "ICE 1043")
        self.assertEqual(leg.origin, "Kitzbühel")

    def test_a_train_leg_needs_no_operator_at_all(self):
        leg = self._leg(
            mode=TransportLeg.Mode.TRAIN,
            operator="",
            service_number="",
            origin="Kitzbühel",
            destination="Innsbruck Hbf",
        )
        self.assertEqual(leg.mode, TransportLeg.Mode.TRAIN)
        self.assertEqual(leg.operator, "")

    def test_station_names_are_not_truncated_to_an_iata_length(self):
        # origin/destination were max_length=8 when this model was Flight-only.
        station = "Frankfurt (Main) Hauptbahnhof"
        self.assertGreater(len(station), 8)
        self.assertEqual(self._leg(origin=station).origin, station)

    def test_mode_does_not_change_the_local_time_helpers(self):
        # The time handling is mode-agnostic: a train renders exactly like a
        # flight did, which is why this is a rename plus a field, not a
        # separate train model.
        leg = self._leg(
            mode=TransportLeg.Mode.TRAIN,
            origin="Boston",
            destination="New York",
            origin_timezone="America/New_York",
            destination_timezone="America/New_York",
            departure_at=datetime.fromisoformat("2026-09-12T14:00:00+00:00"),
            arrival_at=datetime.fromisoformat("2026-09-12T18:30:00+00:00"),
        )
        self.assertEqual(leg.departure_local_str, "10:00 AM EDT")
        self.assertEqual(leg.arrival_local_str, "2:30 PM EDT")

    def test_the_relation_is_renamed_too(self):
        leg = self._leg()
        self.assertEqual(list(self.trip.transport.all()), [leg])
        self.assertFalse(hasattr(self.trip, "flights"))

    def test_legs_for_a_trip_are_ordered_by_departure(self):
        late = self._leg(departure_at=datetime.fromisoformat("2026-09-12T20:00:00+00:00"))
        early = self._leg(departure_at=datetime.fromisoformat("2026-09-12T08:00:00+00:00"))
        self.assertEqual(list(self.trip.transport.all()), [early, late])

    def test_deleting_a_trip_takes_its_legs(self):
        self._leg()
        other = make_trip(name="Other")
        other.transport.create(
            origin="AMS",
            destination="CDG",
            departure_at=datetime.fromisoformat("2026-09-12T08:00:00+00:00"),
            arrival_at=datetime.fromisoformat("2026-09-12T10:00:00+00:00"),
        )
        self.trip.delete()
        self.assertEqual(TransportLeg.objects.count(), 1)

    def test_str_is_still_the_route(self):
        self.assertEqual(
            str(self._leg(service_number="UA1234")), "ABQ to DEN UA1234"
        )

    def test_duration_str_is_readable_not_a_timedelta(self):
        # The card shows elapsed time; a raw timedelta renders as 7:15:00,
        # which is a clock reading, not a duration.
        leg = self._leg(
            arrival_at=datetime.fromisoformat("2026-09-12T18:15:00+00:00"),
        )
        self.assertEqual(leg.duration_str, "4h 15m")

    def test_duration_str_spans_days_when_the_flight_overnights(self):
        leg = self._leg(
            departure_at=datetime.fromisoformat("2026-09-12T14:00:00+00:00"),
            arrival_at=datetime.fromisoformat("2026-09-14T19:30:00+00:00"),
        )
        self.assertEqual(leg.duration_str, "2d 5h 30m")

    def test_duration_str_of_an_exact_hour_omits_the_minutes(self):
        leg = self._leg()
        self.assertEqual(leg.duration_str, "1h")


class TransportLegAdminTests(TestCase):
    def setUp(self):
        self.admin = TransportLegAdmin(TransportLeg, AdminSite())

    def test_mode_is_editable_and_listed(self):
        self.assertIn("mode", TransportLegAdminForm.Meta.fields)
        self.assertIn("mode", self.admin.list_display)
        self.assertIn("mode", self.admin.list_filter)

    def test_the_form_still_excludes_the_utc_fields(self):
        # The point of the form is that departure_at/arrival_at are derived;
        # the rename must not have reintroduced them.
        for field in ("departure_at", "arrival_at"):
            self.assertNotIn(field, TransportLegAdminForm.Meta.fields)

    def test_the_inline_prefix_follows_the_related_name(self):
        # The trip admin's inline is keyed on `transport`, and a stale
        # `flights` prefix would silently drop submitted legs.
        from apps.trips.admin import TripAdmin as _TripAdmin

        inlines = _TripAdmin(Trip, AdminSite()).inlines
        self.assertIn(
            TransportLeg, [inline.model for inline in inlines]
        )


class TripSoftDeleteAdminTests(TestCase):
    """The admin is the only way back to a soft-deleted trip, so it is tested.

    Everywhere else a deleted trip is simply invisible by design, which means
    the changelist and the restore action are the whole recovery story. If
    those quietly stop working, deleted trips become unreachable.
    """

    def setUp(self):
        self.user = User.objects.create_superuser(
            "admin", "admin@example.com", "password"
        )
        self.client.force_login(self.user)
        self.trip = make_trip(name="Live Trip")
        self.gone = make_trip(name="Deleted Trip", start_date=date(2026, 1, 1))

    def test_the_changelist_hides_deleted_trips_by_default(self):
        self.gone.soft_delete()
        response = self.client.get("/admin/trips/trip/")
        self.assertContains(response, "Live Trip")
        self.assertNotContains(response, "Deleted Trip")

    def test_the_filter_brings_a_deleted_trip_back_into_view(self):
        self.gone.soft_delete()
        response = self.client.get("/admin/trips/trip/?deleted=yes")
        self.assertContains(response, "Deleted Trip")
        self.assertNotContains(response, "Live Trip")

    def test_a_deleted_trip_is_still_editable_in_the_admin(self):
        # The point of soft delete: the content survives and staff can read it.
        self.gone.soft_delete()
        response = self.client.get(f"/admin/trips/trip/{self.gone.pk}/change/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Deleted Trip")

    def test_the_restore_action_brings_a_trip_back(self):
        self.gone.soft_delete()
        # The action can only act on what the current changelist selected, and
        # the default list is live-only, so recovery goes through the filter.
        response = self.client.post(
            "/admin/trips/trip/?deleted=yes",
            {
                "action": "restore_trips",
                "_selected_action": [str(self.gone.pk)],
            },
            follow=True,
        )
        self.gone.refresh_from_db()
        self.assertIsNone(self.gone.deleted_at)
        self.assertFalse(self.gone.is_deleted)
        self.assertContains(response, "Restored 1 trip(s).")

    def test_restoring_a_live_trip_changes_nothing_and_says_so(self):
        # A no-op is harmless, but the message must not claim success.
        response = self.client.post(
            "/admin/trips/trip/",
            {
                "action": "restore_trips",
                "_selected_action": [str(self.trip.pk)],
            },
            follow=True,
        )
        self.trip.refresh_from_db()
        self.assertIsNone(self.trip.deleted_at)
        self.assertContains(
            response, "None of the selected trips were deleted."
        )
