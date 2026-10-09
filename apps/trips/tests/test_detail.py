"""Tests for the trip detail page.

Two things are pinned here. The first is that every ``section_type`` has a
layout, because the alternative is a day that renders half-empty and nobody
notices until they print it. The second is that the page holds a fixed query
count: a trip is 17 days and ~70 sections, so an unprefetched page is a hundred
queries, and that is exactly the kind of thing that looks fine locally and
falls over on the box.

The section payloads are built by hand rather than imported, so a change to
``docx_import`` cannot quietly move these expectations.
"""


from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.trips.models import TripRole
from apps.trips.models import (
    BookingTask,
    Contact,
    Day,
    Lodging,
    Meal,
    Section,
    TransportLeg,
    Traveler,
    Trip,
    TripGrant,
)

User = get_user_model()


def section(day, section_type, content, **kwargs):
    """Create a Section.

    ``content`` is passed through as a Python object, not dumped to a string:
    ``Section.content`` is a JSONField, so ``json.dumps`` would store a JSON
    *string scalar* and every ``section.content.<key>`` lookup in the template
    would then resolve to nothing.
    """
    kwargs.setdefault("title", "")
    return Section.objects.create(
        day=day,
        section_type=section_type,
        content=content,
        order=kwargs.pop("order", 0),
        **kwargs,
    )


class DetailFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            "staffy", "staffy@example.com", "pw-1234-abcd", is_staff=True
        )
        cls.reader = User.objects.create_user("ada", "ada@example.com", "pw-1234-abcd")

        cls.trip = Trip.objects.create(
            name="Taos / Angel Fire",
            destination="New Mexico",
            start_date=date(2026, 9, 12),
            end_date=date(2026, 9, 19),
            status=Trip.Status.STARTING,
        )
        TripGrant.objects.create(trip=cls.trip, user=cls.reader, role=TripRole.VIEWER)
        cls.day = Day.objects.create(
            trip=cls.trip,
            day_number=1,
            date=date(2026, 9, 12),
            theme="Arrival",
            meals_included=True,
        )

    def setUp(self):
        self.client.force_login(self.reader)

    def get(self, trip=None):
        return self.client.get(reverse("trips:trip_detail", args=[(trip or self.trip).pk]))


class SectionLayoutTests(DetailFixture):
    def test_phase_renders_heading_summary_and_highlights(self):
        section(
            self.day,
            Section.Type.PHASE,
            {
                "heading": "Morning",
                "summary": "We start early.",
                "highlights": ["Hike up", "Swim"],
            },
        )
        html = self.get().content.decode()
        self.assertIn("Morning", html)
        self.assertIn("We start early.", html)
        self.assertIn("Hike up", html)
        self.assertIn("Swim", html)
        # Prose sections are cards now; the grid-backed ones (logistics, CYA,
        # meals) keep a plain wrapper so their row cards are never nested.
        self.assertIn('<div class="section card">', html)

    def test_logistics_table_renders_a_header_and_every_row(self):
        section(
            self.day,
            Section.Type.LOGISTICS_TABLE,
            {"columns": ["Time", "Stop", "Details"], "rows": [["9:00", "Taos", "Drive"], ["13:00", "Gorge", "Lunch"]]},
        )
        html = self.get().content.decode()
        for cell in ("Time", "Stop", "Details", "9:00", "Taos", "Drive", "13:00", "Gorge", "Lunch"):
            self.assertIn(cell, html)

    def test_callout_renders_its_tone_and_text(self):
        section(
            self.day,
            Section.Type.CALLOUT,
            {"tone": "warning", "text": "The road closes at dusk."},
        )
        html = self.get().content.decode()
        self.assertIn("callout-warning", html)
        self.assertIn("The road closes at dusk.", html)

    def test_choose_your_adventure_renders_every_option(self):
        section(
            self.day,
            Section.Type.CHOOSE_YOUR_ADVENTURE,
            {
                "prompt": "Pick one",
                "options": [
                    {"title": "Rafting", "description": "Class III.", "duration": "3 hrs", "cost": "$85"},
                    {"title": "Hot springs", "description": "Soak."},
                ],
            },
        )
        html = self.get().content.decode()
        self.assertIn("Pick one", html)
        self.assertIn("Rafting", html)
        self.assertIn("Class III.", html)
        self.assertIn("3 hrs", html)
        self.assertIn("$85", html)
        # Second option has no duration/cost keys at all.
        self.assertIn("Hot springs", html)
        self.assertIn("Soak.", html)

    def test_free_text_renders_every_paragraph(self):
        section(
            self.day,
            Section.Type.FREE_TEXT,
            {"paragraphs": ["First thought.", "Second thought."]},
        )
        html = self.get().content.decode()
        self.assertIn("First thought.", html)
        self.assertIn("Second thought.", html)
        self.assertIn('<div class="section card prose-block">', html)

    def test_an_unknown_section_type_shows_a_placeholder_rather_than_vanishing(self):
        Section.objects.create(
            day=self.day,
            section_type="itinerary_timeline",
            title="A type we do not render yet",
            content={},
            order=0,
        )
        html = self.get().content.decode()
        self.assertIn("No layout for this section type yet.", html)
        self.assertIn("A type we do not render yet", html)


class MissingKeyToleranceTests(DetailFixture):
    """The payload contract says renderers must tolerate absent keys.

    The importer adds keys over time and Europe already emits
    choose_your_adventure payloads carrying heading/summary/highlights that the
    documented shape does not list, so neither a missing key nor a surplus one
    may raise.
    """

    def test_phase_with_only_a_heading(self):
        section(self.day, Section.Type.PHASE, {"heading": "Bare"})
        self.assertEqual(self.get().status_code, 200)

    def test_logistics_table_with_no_rows(self):
        section(self.day, Section.Type.LOGISTICS_TABLE, {"columns": ["A", "B"], "rows": []})
        self.assertEqual(self.get().status_code, 200)

    def test_logistics_table_with_no_columns(self):
        section(self.day, Section.Type.LOGISTICS_TABLE, {"rows": [["only"]]})
        self.assertEqual(self.get().status_code, 200)

    def test_callout_with_no_tone_falls_back(self):
        section(self.day, Section.Type.CALLOUT, {"text": "No tone given."})
        html = self.get().content.decode()
        self.assertIn("callout-info", html)
        self.assertIn("No tone given.", html)

    def test_choose_your_adventure_with_surplus_keys(self):
        # Exactly what the Europe importer emits.
        section(
            self.day,
            Section.Type.CHOOSE_YOUR_ADVENTURE,
            {
                "prompt": "Afternoon",
                "heading": "Afternoon",
                "summary": "",
                "highlights": [],
                "options": [{"title": "Only a title"}],
            },
        )
        html = self.get().content.decode()
        self.assertIn("Only a title", html)

    def test_empty_content_object(self):
        for kind in Section.Type.values:
            section(self.day, kind, {})
        self.assertEqual(self.get().status_code, 200)

    def test_a_day_with_no_sections_still_renders(self):
        other = Day.objects.create(trip=self.trip, day_number=2, date=date(2026, 9, 13))
        self.assertEqual(self.get().status_code, 200)
        self.assertIn("Day 2", self.get().content.decode())


# The fixture trip is Sep 12-19, 2026; pin "today" before it so these tests see the
# planning-stage badge rather than "Completed" (see CompletedTripTests).
@mock.patch("apps.trips.models.django_timezone.localdate", new=lambda: date(2026, 9, 1))
class TripChromeTests(DetailFixture):
    def test_header_carries_name_dates_and_draft_badge(self):
        html = self.get().content.decode()
        self.assertIn("Taos / Angel Fire", html)
        self.assertIn("Sep 12", html)
        self.assertIn("Sep 19, 2026", html)
        self.assertIn("badge-draft", html)

    def test_a_ready_trip_is_badged_ready(self):
        self.trip.status = Trip.Status.READY_TO_GO
        self.trip.save()
        self.assertIn("badge-ready", self.get().content.decode())

    def test_the_header_card_carries_status_dates_and_travellers(self):
        # The header is a card now: title row with the status badge, a kicker
        # dl of dates/nights/destination, and travellers as chips. Pinned so a
        # future layout pass cannot quietly drop the roster off the front page.
        ada = Traveler.objects.create(name="Ada Lovelace")
        self.trip.travelers.add(ada)
        html = self.get().content.decode()
        self.assertIn("card-kicker", html)
        self.assertIn("badge-draft", html)
        self.assertIn("Starting", html)  # the real stage, not a generic "Draft"
        self.assertIn("Sep 12", html)
        self.assertIn("Sep 19, 2026", html)
        self.assertIn("New Mexico", html)
        self.assertIn("Ada Lovelace", html)
        self.assertIn('class="chip"', html)

    def test_transport_shows_local_times_not_utc(self):
        TransportLeg.objects.create(
            trip=self.trip,
            mode="plane",
            origin="BWI",
            destination="DEN",
            origin_timezone="America/New_York",
            destination_timezone="America/Denver",
            departure_at="2026-09-12T14:00:00Z",
            arrival_at="2026-09-12T16:15:00Z",
        )
        html = self.get().content.decode()
        # 14:00Z in New York is 10:00 EDT — if this rendered 14:00 the template
        # piped an aware datetime through |date and silently reverted to UTC.
        self.assertIn("10:00 AM EDT", html)
        self.assertIn("10:15 AM MDT", html)

    def test_lodging_shows_dates_and_confirmation(self):
        Lodging.objects.create(
            trip=self.trip,
            name="Hotel Taos",
            check_in=date(2026, 9, 12),
            check_out=date(2026, 9, 19),
            confirmation_number="ABC123",
        )
        html = self.get().content.decode()
        self.assertIn("Hotel Taos", html)
        self.assertIn("ABC123", html)

    def test_transport_card_carries_cost_duration_and_notes(self):
        # These are the fields the old compact table had no column for; if a
        # future layout pass drops back to columns, this fails rather than
        # quietly losing the price off the printed page.
        TransportLeg.objects.create(
            trip=self.trip,
            mode="plane",
            origin="BWI",
            destination="DEN",
            departure_at="2026-09-12T14:00:00Z",
            arrival_at="2026-09-12T17:45:00Z",
            cost="249.50",
            notes="Seats chosen at check-in.",
        )
        html = self.get().content.decode()
        self.assertIn("249.50", html)
        self.assertIn("3h 45m", html)
        self.assertIn("Seats chosen at check-in.", html)

    def test_lodging_card_carries_rate_and_notes(self):
        Lodging.objects.create(
            trip=self.trip,
            name="Hotel Taos",
            check_in=date(2026, 9, 12),
            check_out=date(2026, 9, 19),
            nightly_rate="189.00",
            notes="Parking is extra.",
        )
        html = self.get().content.decode()
        self.assertIn("189.00", html)
        self.assertIn("Parking is extra.", html)

    def test_meal_card_carries_reservation_notes(self):
        Meal.objects.create(
            day=self.day,
            name="Los Arboles",
            meal_type=Meal.MealType.DINNER,
            price_range="$$",
            reservation_notes="Book 6pm, patio.",
        )
        html = self.get().content.decode()
        self.assertIn("Book 6pm, patio.", html)

    def test_quick_reference_lists_confirmations_and_contacts(self):
        from apps.trips.models import Confirmation

        Confirmation.objects.create(trip=self.trip, label="Hotel", confirmation_number="XYZ789")
        Contact.objects.create(trip=self.trip, name="Front desk", phone="555-0100")
        html = self.get().content.decode()
        self.assertIn("Quick reference", html)
        self.assertIn("XYZ789", html)
        self.assertIn("Front desk", html)
        self.assertIn("555-0100", html)

    def test_outstanding_booking_tasks_are_shown_and_done_ones_are_not(self):
        BookingTask.objects.create(trip=self.trip, title="Book the flights", priority=1)
        BookingTask.objects.create(trip=self.trip, title="Already done", priority=4, done=True)
        html = self.get().content.decode()
        self.assertIn("Book the flights", html)
        self.assertNotIn("Already done", html)

    def test_task_priority_drives_the_badge_colour(self):
        # Same card grid, four badge classes: colour is how the list ranks at a
        # glance. IntegerChoices are compared as ints, so `task.priority == 1`
        # matches the stored value.
        BookingTask.objects.create(trip=self.trip, title="Flights", priority=1)
        BookingTask.objects.create(trip=self.trip, title="Trains", priority=2)
        BookingTask.objects.create(trip=self.trip, title="Hotels", priority=3)
        BookingTask.objects.create(trip=self.trip, title="Insurance", priority=4)
        html = self.get().content.decode()
        self.assertIn('<span class="badge badge-critical">Critical</span>', html)
        self.assertIn('<span class="badge badge-high">High</span>', html)
        self.assertIn('<span class="badge badge-medium">Medium</span>', html)
        self.assertIn('<span class="badge badge-low">Low</span>', html)
        self.assertIn('<div class="card-grid">', html)

    def test_meals_render_for_the_day(self):
        Meal.objects.create(
            day=self.day,
            name="Los Arboles",
            meal_type=Meal.MealType.DINNER,
            price_range="$$",
            why_recommended="Green chile stew.",
        )
        html = self.get().content.decode()
        self.assertIn("Los Arboles", html)
        self.assertIn("Green chile stew.", html)
        self.assertIn("$$", html)

    def test_a_split_day_says_so(self):
        split = Day.objects.create(trip=self.trip, day_number=3, date=date(2026, 9, 14))
        ada = Traveler.objects.create(name="Ada")
        split.travelers.add(ada)
        html = self.get().content.decode()
        self.assertIn("Split group", html)
        self.assertIn(ada.name, html)

    def test_a_whole_trip_day_does_not_claim_to_be_split(self):
        html = self.get().content.decode()
        self.assertNotIn("Split group", html)

    def test_a_trip_with_no_days_says_so(self):
        Day.objects.all().delete()
        self.assertIn("No days have been planned yet.", self.get().content.decode())


class QueryCountTests(DetailFixture):
    """The page must not cost a query per section, meal or day.

    Sixteen days and thirty sections here; the assertion is on the total, so a
    future N+1 shows up as a failing number rather than as a slow page someone
    notices on the box.
    """

    def test_a_multi_day_trip_holds_a_fixed_query_count(self):
        ada = Traveler.objects.create(name="Ada")
        for offset in range(1, 16):
            day = Day.objects.create(
                trip=self.trip,
                day_number=offset + 1,
                date=self.trip.start_date + timedelta(days=offset),
            )
            section(
                day,
                Section.Type.LOGISTICS_TABLE,
                {"columns": ["Time", "Stop"], "rows": [["9:00", "Somewhere"], ["12:00", "Elsewhere"]]},
                order=offset,
            )
            Meal.objects.create(day=day, name=f"Dinner {offset}", meal_type=Meal.MealType.DINNER)
            day.travelers.add(ada)

        # The comment threads add a few fixed queries:
        #
        # * 1 for the four content types, fetched together with
        #   `get_for_models` — `get_for_model` is one query per model, so four
        #   kinds would have cost four.
        # * 1 for every comment on the trip, across all four target kinds at
        #   once. A `GenericPrefetch` cannot cover this: the targets are reached
        #   through three different relations, and querying per day would cost one
        #   query per day.
        # * 1 for `Trip.can(user, "comment")` — the grant (and its role) lookup
        #   inside the existing rule. Deliberately not reimplemented here; the
        #   trip list and `can_create_trip` already treat `capabilities_for` as
        #   the single place the rule lives, and staff would cost none at all.
        #   (It was 2 when the role lived on the user, as `accounts.UserRole`.)
        #
        # All are fixed: the count does not move with the number of days,
        # sections, meals or comments, which is the property being pinned.
        #
        # 19 in all on this site, four of which are the site shell's, added to
        # every page — UserTimezoneMiddleware (user_preferences),
        # UserThemeMiddleware (account_settings), and the travel_preferences and
        # rewards context processors. None of them depends on the trip.
        with self.assertNumQueries(19):
            response = self.get()
        self.assertEqual(response.status_code, 200)



class CompletedTripTests(DetailFixture):
    """A trip whose end date has passed is Completed, offers to tick it off the
    bucket list, and moves to "Past trips" on the list."""

    @mock.patch("apps.trips.models.django_timezone.localdate", return_value=date(2026, 9, 20))
    def test_finished_trip(self, _today):
        html = self.get().content.decode()
        self.assertIn("badge-done", html)
        self.assertIn("Completed", html)
        self.assertIn(reverse("bucketlists:trip_done", args=[self.trip.pk]), html)
        listing = self.client.get(reverse("trips:trip_list"))
        self.assertEqual((listing.context["upcoming"], listing.context["past"]), ([], [self.trip]))
        self.assertContains(listing, "Past trips")

    @mock.patch("apps.trips.models.django_timezone.localdate", return_value=date(2026, 9, 19))
    def test_last_day_is_not_finished_yet(self, _today):
        html = self.get().content.decode()
        self.assertNotIn("badge-done", html)
        self.assertNotIn(reverse("bucketlists:trip_done", args=[self.trip.pk]), html)
