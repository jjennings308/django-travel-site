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


import re
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.trips.models import TripRole
from apps.trips.models import (
    BookingTask,
    Confirmation,
    Contact,
    Day,
    ItemLink,
    Lodging,
    Meal,
    Section,
    TaskOption,
    TransportLeg,
    Traveler,
    Trip,
    TripActivity,
    TripInfo,
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
        stay = Lodging.objects.create(
            trip=self.trip,
            name="Hotel Taos",
            check_in=date(2026, 9, 12),
            check_out=date(2026, 9, 19),
        )
        # Phase B: the number is a Confirmation linked to the stay, shown as a chip on it.
        Confirmation.attach_number(self.trip, "ABC123", stay)
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
        self.assertIn('id="reference"', html)  # Reference (U2) is the home of confirmations and contacts
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
        # One list in Reference, four badge classes: colour is how the list ranks at a
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
        self.assertIn('id="still-to-book"', html)

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
        # R18: every meal and section linked to a catalogue place (and activity) — no extra query.
        from apps.activities.models import Activity, ActivityCategory
        from apps.locations.models import POI, City, Country
        country = Country.objects.create(name="Testland", slug="tl", iso_code="TL", iso3_code="TLD", continent="Europe")
        city = City.objects.create(name="Testville", slug="testville", country=country, latitude=1, longitude=1)
        place = POI.objects.create(name="Old Bakery", slug="old-bakery", city=city, latitude=1, longitude=1)
        catalogue_activity = Activity.objects.create(
            name="Bread tour", slug="bread-tour", description="x",
            category=ActivityCategory.objects.create(name="Food", slug="food-cat"))
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
            Meal.objects.create(day=day, name=f"Dinner {offset}", meal_type=Meal.MealType.DINNER, poi=place)
            day.sections.update(poi=place, activity=catalogue_activity)
            day.travelers.add(ada)
            # Phase A: legs shown on their day cost nothing either — one placed in a travel
            # section, one in the day's automatic block, both from the one transport prefetch.
            travel = section(day, Section.Type.TRAVEL, {"rows": [["Ticket", "Bayern Ticket"]],
                                                       "columns": ["What", "Info"]}, order=offset + 100)
            TransportLeg.objects.create(trip=self.trip, date=day.date, origin="A", destination="B",
                                        section=travel, est_duration=timedelta(minutes=45))
            TransportLeg.objects.create(trip=self.trip, date=day.date, origin="B", destination="C", order=2)
            # Phase B: a confirmation per day covering its legs and meal, one more for a stay.
            confirmation = Confirmation.objects.create(trip=self.trip, confirmation_number=f"PNR{offset}",
                                                       provider="Delta")
            for item in [*TransportLeg.objects.filter(trip=self.trip, date=day.date), *day.meals.all(),
                         *day.sections.all()]:
                confirmation.link(item)
            confirmation.travelers.add(ada)
            # Activities (TripActivity): two per day, with their place, travellers and a
            # confirmation each — still two fixed queries for the lot.
            for n in range(2):
                activity = TripActivity.objects.create(trip=self.trip, day=day, title=f"Tour {offset}-{n}",
                                                       place_text="Ghost Ranch", order=n)
                activity.travelers.add(ada)
                confirmation.link(activity)
            # Phase E: a booking task about the day's leg, and a not-yet-booked flight.
            BookingTask.objects.create(trip=self.trip, title=f"Seats A to B {offset}",
                                       leg=TransportLeg.objects.filter(trip=self.trip, date=day.date).first())
            TransportLeg.objects.create(trip=self.trip, date=day.date, origin="X", destination="Y", mode="plane",
                                        order=3)

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
        # * 1 for the trip's catalogue cities (the chips under the title). Each
        #   day's city comes with the days query (select_related), so it is free.
        #
        # 27 in all on this site, four of which are the site shell's, added to
        # every page — UserTimezoneMiddleware (user_preferences),
        # UserThemeMiddleware (account_settings), and the travel_preferences and
        # rewards context processors. None of them depends on the trip.
        # * 2 for the confirmations' links (with their content type) and travellers. A link is
        #   generic, like a comment: the items it points at (legs, stays, the days' sections and
        #   meals) are already on the page, so views._attach_confirmations resolves them in
        #   Python. Phase B's three per-kind tables cost one query each; generic links are one,
        #   so the pin went down deliberately from 24 to 22 (with the content-type cache warmed
        #   below: run alone, a cold cache added one query and the count depended on test order).
        # * 2 for the days' activities (TripActivity, with their place) and their travellers.
        #   Raised deliberately from 22 to 24.
        # * 2 for contacts and info notes linked to items (U4): the trip's item links (with both
        #   content types) and its info notes. Resolved in Python (itinerary.attach_links), so
        #   fixed however many links. Raised deliberately from 24 to 26.
        # * 1 for the booking tasks' options (decisions, U6), however many tasks and options.
        #   Raised deliberately from 26 to 27.
        stay = Lodging.objects.create(trip=self.trip, name="Hotel", check_in=self.trip.start_date,
                                      check_out=self.trip.start_date + timedelta(days=2))
        Confirmation.objects.create(trip=self.trip, confirmation_number="HOTEL1").link(stay)
        # Tickets and documents (R5): files on several confirmations, still one query.
        from apps.trips.models import ConfirmationFile
        for confirmation in Confirmation.objects.filter(trip=self.trip)[:4]:
            for n in range(2):
                ConfirmationFile.objects.create(confirmation=confirmation, file=f"trips/x/{confirmation.pk}-{n}.pdf",
                                                original_name=f"ticket-{n}.pdf", content_type="application/pdf",
                                                size=1000)
        # Phase E: tasks on items, a suggestion and the "Not booked yet" list are worked out in
        # Python from the rows above (apps/trips/booking_tasks.py): no query of their own.
        BookingTask.objects.create(trip=self.trip, title="Hotel deposit", stay=stay)
        for n in range(3):
            decision = BookingTask.objects.create(trip=self.trip, title=f"Pick hotel {n}", kind="decide")
            for m in range(3):
                TaskOption.objects.create(task=decision, title=f"Option {n}-{m}", chosen=(m == 0), order=m)
        desk = Contact.objects.create(trip=self.trip, name="Front desk", phone="+1 555 0100")
        rules = TripInfo.objects.create(trip=self.trip, title="Ticket rules", body="Regional only.")
        ItemLink.link(desk, stay)
        for day in self.trip.days.all():
            ItemLink.link(rules, day)
            for leg in TransportLeg.objects.filter(trip=self.trip, date=day.date):
                ItemLink.link(desk, leg)
        BookingTask.objects.create(trip=self.trip, title="Pay the Hotel balance")  # suggests the stay
        Lodging.objects.create(trip=self.trip, name="Inn", check_in=self.trip.start_date,
                               check_out=self.trip.start_date + timedelta(days=1))  # not booked yet
        from django.contrib.contenttypes.models import ContentType
        ContentType.objects.get_for_models(Trip, Day, Section, BookingTask)  # the comments' kinds, as in a warm process
        # Checklists (R9) on several lists, with per-person ticks: still three queries.
        from apps.trips.models import Checklist, ChecklistItem, ChecklistTick
        self.trip.travelers.add(ada)
        for n in range(3):
            checklist = Checklist.objects.create(trip=self.trip, title=f"List {n}", kind="documents")
            for m in range(4):
                item = ChecklistItem.objects.create(checklist=checklist, text=f"Item {m}", per_person=bool(m % 2))
                if m % 2:
                    ChecklistTick.objects.create(item=item, traveler=ada)
        # Costs in other currencies (R10): the Overview's estimate converts them — two queries
        # (the ECB rates and the trip's own rates), however many costs there are.
        for n, currency in enumerate(["EUR", "GBP", "EUR"]):
            Confirmation.objects.create(trip=self.trip, confirmation_number=f"COST{n}", cost=100 + n,
                                        currency=currency)
        # 32 = 27 + confirmation files (R5) + checklists, items, ticks (R9) + rates, trip rates (R10)
        # - the rewards context processor's query on every page (removed in R11)
        # - UserTimezoneMiddleware's own query: since R21 it reads the same AccountSettings row as
        #   UserThemeMiddleware (it used to read the deprecated UserPreferences) = 31.
        with self.assertNumQueries(32):  # 31 + the catalogue notes of its linked items (catalogue-notes N2)
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


class CountdownTests(DetailFixture):
    """The trip list's cards count down to the start (the trip runs Sep 12–19, 2026)."""

    def countdown(self, today):
        with mock.patch("apps.trips.models.django_timezone.localdate", return_value=today):
            listing = self.client.get(reverse("trips:trip_list"))
        found = re.search(r"<p [^>]*data-countdown>([^<]*)</p>", listing.content.decode())
        return found.group(1) if found else None

    def test_before_during_and_after(self):
        self.assertEqual(self.countdown(date(2026, 8, 13)), "In 30 days")
        self.assertEqual(self.countdown(date(2026, 9, 11)), "Tomorrow")
        self.assertEqual(self.countdown(date(2026, 9, 12)), "Starts today")
        self.assertEqual(self.countdown(date(2026, 9, 19)), "Underway")
        self.assertIsNone(self.countdown(date(2026, 9, 20)))


class HeaderActionTests(DetailFixture):
    """Edit/Delete on the trip page itself, shown only to those who may use them."""

    def actions(self):
        html = self.get().content.decode()
        return (reverse("trips:trip_edit", args=[self.trip.pk]) in html,
                reverse("trips:trip_delete", args=[self.trip.pk]) in html)

    def test_viewer_and_commentor_get_neither(self):
        self.assertEqual(self.actions(), (False, False))
        TripGrant.objects.filter(trip=self.trip, user=self.reader).update(role=TripRole.COMMENTOR)
        self.assertEqual(self.actions(), (False, False))

    def test_editor_gets_edit_and_owner_also_delete(self):
        TripGrant.objects.filter(trip=self.trip, user=self.reader).update(role=TripRole.EDITOR)
        self.assertEqual(self.actions(), (True, False))
        Trip.objects.filter(pk=self.trip.pk).update(created_by=self.reader)
        self.assertEqual(self.actions(), (True, True))

    def test_staff_get_both(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.actions(), (True, True))


class ShareTripTests(DetailFixture):
    """Editors turn a trip's public link on and off from the trip page."""

    def test_viewer_cannot_share_but_sees_an_existing_link(self):
        self.assertNotIn(reverse("trips:trip_share", args=[self.trip.pk]), self.get().content.decode())
        self.assertEqual(self.client.post(reverse("trips:trip_share", args=[self.trip.pk])).status_code, 403)
        token = self.trip.enable_public()
        html = self.get().content.decode()
        self.assertIn(reverse("public_trip", args=[token]), html)
        self.assertNotIn(reverse("trips:trip_unshare", args=[self.trip.pk]), html)

    def test_editor_shares_and_unshares(self):
        TripGrant.objects.filter(trip=self.trip, user=self.reader).update(role=TripRole.EDITOR)
        self.assertIn(reverse("trips:trip_share", args=[self.trip.pk]), self.get().content.decode())
        self.client.post(reverse("trips:trip_share", args=[self.trip.pk]))
        self.trip.refresh_from_db()
        token = self.trip.public_token
        self.assertIsNotNone(token)
        self.client.post(reverse("trips:trip_share", args=[self.trip.pk]))  # again: same link kept
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.public_token, token)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("public_trip", args=[token])).status_code, 200)
        self.client.force_login(self.reader)
        self.client.post(reverse("trips:trip_unshare", args=[self.trip.pk]))
        self.trip.refresh_from_db()
        self.assertIsNone(self.trip.public_token)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("public_trip", args=[token])).status_code, 404)

    def test_no_grant_is_404_and_get_is_refused(self):
        stranger = User.objects.create_user("bob", "bob@example.com", "pw-1234-abcd")
        self.client.force_login(stranger)
        self.assertEqual(self.client.post(reverse("trips:trip_share", args=[self.trip.pk])).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("trips:trip_share", args=[self.trip.pk])).status_code, 405)

    def test_query_count_unchanged_when_shared(self):
        self.trip.enable_public()
        self.client.force_login(self.admin)
        with self.assertNumQueries(len(self._baseline_queries())):
            self.get()

    def _baseline_queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.trip.revoke_public()
        with CaptureQueriesContext(connection) as ctx:
            self.get()
        self.trip.enable_public()
        return ctx.captured_queries
