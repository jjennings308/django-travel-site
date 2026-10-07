"""The public, non-detailed view.

Two kinds of test, and the second kind is the one that matters.

The first pins behaviour: tokens, 404s, revocation, the URL. Those are cheap and
they break loudly.

The second pins **absence**. `test_no_real_traveller_name_reaches_the_public_page`
runs the serializer over every row in the real database and asserts that no
traveller's name appears anywhere in the output. It is the test that would have
caught `Day.theme`, which leaked in 4 of 17 real days before it was dropped, and
it is written against production data rather than fixtures on purpose: synthetic
fixtures are only ever as honest as the fixture author, and the leaks here were
all in prose that a made-up trip would never contain.
"""

import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase
from django.urls import reverse

from trips.models import (
    BookingTask,
    Comment,
    Confirmation,
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
from trips.public import (
    DAY_FIELDS,
    MEAL_FIELDS,
    TRIP_FIELDS,
    find_leaks,
    public_trip,
    trip_leak_finders,
)

User = get_user_model()


class PublicFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.trip = Trip.objects.create(
            name="James & Regan — Taos",
            destination="Taos / Angel Fire, New Mexico",
            start_date=date(2026, 9, 12),
            end_date=date(2026, 9, 19),
            budget=Trip.Budget.MODERATE,
            structure=Trip.Structure.SEMI_GUIDED,
            notes="Booked under James Jennings. Passport in the red folder.",
        )
        cls.token = cls.trip.enable_public()

        james = Traveler.objects.create(name="James Jennings", passport_country="US")
        regan = Traveler.objects.create(name="Regan Jennings")
        cls.trip.travelers.add(james, regan)

        cls.day = Day.objects.create(
            trip=cls.trip,
            day_number=1,
            date=date(2026, 9, 12),
            theme="Arrival & Santa Fe Evening",
            meals_included=True,
        )
        # Prose that must never be published, one row per model.
        Section.objects.create(
            day=cls.day,
            section_type=Section.Type.PHASE,
            order=1,
            content={"heading": "Departure", "summary": "James and Regan leave together"},
        )
        Meal.objects.create(
            day=cls.day,
            name="Rancho de Chimayó",
            meal_type=Meal.MealType.DINNER,
            cuisine="New Mexican",
            price_range="$$",
            why_recommended="James Beard Award winner, family-run since 1965",
            reservation_notes="Book under James Jennings, 8pm",
        )
        Lodging.objects.create(
            trip=cls.trip,
            name="Hotel Chimayo",
            check_in=date(2026, 9, 12),
            check_out=date(2026, 9, 15),
            confirmation_number="5305434791",
            notes="Room: Junior Suite · Guest Name: James Jennings",
        )
        TransportLeg.objects.create(
            trip=cls.trip,
            mode=TransportLeg.Mode.PLANE,
            operator="Delta",
            service_number="DL 447",
            confirmation_number="GCH7JS",
            origin="PIT",
            destination="DEN",
            departure_at="2026-09-12T14:00:00Z",
            arrival_at="2026-09-12T16:00:00Z",
        )
        Confirmation.objects.create(
            trip=cls.trip, label="Flights (Delta, all 4 legs)", confirmation_number="GCH7JS"
        )
        Contact.objects.create(trip=cls.trip, name="Regan's mom", phone="555-0100")
        cls.task = BookingTask.objects.create(trip=cls.trip, title="fix Regan status")

    def resolve(self):
        """The trip as the view resolves it from the token."""
        from django.shortcuts import get_object_or_404

        return get_object_or_404(
            Trip.objects.public(self.token).prefetch_related(
                "days__meals", "days__sections"
            )
        )


class TokenTests(PublicFixture):
    def test_the_token_makes_the_page_public(self):
        response = self.client.get(reverse("public_trip", args=[self.token]))
        self.assertEqual(response.status_code, 200)

    def test_the_page_needs_no_account(self):
        # Not logged in, and it still renders. That is the feature; it is worth
        # asserting so a stray `login_required` is caught rather than assumed.
        self.assertFalse(self.client.session.get("_auth_user_id"))
        response = self.client.get(reverse("public_trip", args=[self.token]))
        self.assertEqual(response.status_code, 200)

    def test_a_trip_with_no_token_has_no_public_page(self):
        other = Trip.objects.create(
            name="Private", start_date=date(2027, 1, 1), end_date=date(2027, 1,2)
        )
        # Not even the pk resolves it: the URL carries a UUID, and an unissued
        # one is simply a 404.
        self.assertEqual(Trip.objects.public(other.pk).count(), 0)

    def test_an_unknown_token_is_a_404_not_a_403(self):
        stranger = "11111111-2222-3333-4444-555555555555"
        response = self.client.get(reverse("public_trip", args=[stranger]))
        # A 403 would confirm that a token exists.
        self.assertEqual(response.status_code, 404)

    def test_a_soft_deleted_trip_stops_being_public(self):
        # A link somebody already shared must not keep publishing a trip that
        # was deliberately removed.
        self.trip.soft_delete()
        response = self.client.get(reverse("public_trip", args=[self.token]))
        self.assertEqual(response.status_code, 404)

    def test_revoking_removes_the_page_and_leaves_the_trip(self):
        self.trip.revoke_public()
        self.assertEqual(
            self.client.get(reverse("public_trip", args=[self.token])).status_code, 404
        )
        self.assertTrue(Trip.objects.filter(pk=self.trip.pk).exists())
        self.assertEqual(self.trip.days.count(), 1)

    def test_enabling_twice_keeps_the_link_alive(self):
        # Idempotent on purpose: opening this twice must not break a link that
        # has already been pasted somewhere.
        self.assertEqual(self.trip.enable_public(), self.token)

    def test_rotating_invalidates_the_old_link(self):
        old = self.trip.public_token
        self.trip.rotate_public_token()
        self.assertEqual(
            self.client.get(reverse("public_trip", args=[old])).status_code, 404
        )
        self.assertEqual(
            self.client.get(reverse("public_trip", args=[self.trip.public_token])).status_code,
            200,
        )

    def test_the_pk_does_not_resolve(self):
        # Countability is why the URL carries a UUID. This is the test that says
        # so, rather than leaving it to a code comment.
        response = self.client.get("/public/%s/" % self.trip.pk)
        self.assertEqual(response.status_code, 404)

    def test_grants_and_roles_are_irrelevant(self):
        # A public token is access on its own: no grant, no role, no account. If
        # this ever needs a grant to work, the view is wrong.
        stranger = User.objects.create_user("nosey", "nosey@example.com", "pw-1234-abcd")
        self.assertFalse(TripGrant.objects.filter(trip=self.trip, user=stranger).exists())
        self.client.force_login(stranger)
        self.assertEqual(
            self.client.get(reverse("public_trip", args=[self.token])).status_code, 200
        )


class DerivedTitleTests(PublicFixture):
    def test_the_public_title_is_the_destination_and_the_dates(self):
        # `Trip.name` is "James & Regan — Taos" and cannot head a public page.
        self.assertNotIn("James", self.trip.public_title)
        self.assertNotIn("Regan", self.trip.public_title)
        self.assertIn("Taos / Angel Fire", self.trip.public_title)
        self.assertIn("September 12", self.trip.public_title)

    def test_a_trip_with_no_destination_still_gets_a_heading(self):
        bare = Trip.objects.create(
            name="Secret", start_date=date(2027, 3, 1), end_date=date(2027, 3, 8)
        )
        self.assertEqual(bare.public_title, "March 1 – 8, 2027")

    def test_a_single_day_trip_reads_as_one_date(self):
        same = Trip.objects.create(
            name="Same", start_date=date(2027, 3, 1), end_date=date(2027, 3, 1)
        )
        self.assertEqual(same.public_dates, "March 1, 2027")


class ShapeTests(PublicFixture):
    """The output is a subset of the declared allowlist. Nothing else."""

    def get_shape(self):
        return public_trip(self.resolve())

    def test_the_keys_are_the_ones_that_were_chosen(self):
        shape = self.get_shape()
        # `title`, `nights`, `budget`, `structure` and `days` are derived or
        # labelled rather than copied, so the allowlist covers the raw columns
        # and these are checked by name here.
        for key in ("title", "nights", "budget", "structure", "days"):
            self.assertIn(key, shape)
        self.assertLessEqual(set(shape) - {"title", "nights", "budget", "structure", "days"},
                             set(TRIP_FIELDS))

    def test_a_day_is_a_subset_of_the_day_allowlist(self):
        day = self.get_shape()["days"][0]
        derived = {"activity_count", "meals"}
        self.assertLessEqual(set(day) - derived, set(DAY_FIELDS))
        self.assertNotIn("theme", day)
        self.assertNotIn("travelers", day)

    def test_a_meal_is_a_subset_of_the_meal_allowlist(self):
        meal = self.get_shape()["days"][0]["meals"][0]
        self.assertLessEqual(set(meal), set(MEAL_FIELDS))
        self.assertNotIn("why_recommended", meal)
        self.assertNotIn("reservation_notes", meal)

    def test_the_output_is_json_serialisable(self):
        # The point of dicts rather than a template: an API reads this verbatim.
        # `DjangoJSONEncoder` rather than the default because dates come through
        # as `date` objects for `|date` to format.
        json.dumps(self.get_shape(), cls=DjangoJSONEncoder)

    def test_the_shape_carries_no_prose_at_all(self):
        # Every value is a date, an int, a bool, a choice label or a short
        # proper noun. This is the property that makes "structure yes, prose no"
        # checkable rather than aspirational.
        def walk(value, path="root"):
            if isinstance(value, dict):
                for key, inner in value.items():
                    walk(inner, f"{path}.{key}")
            elif isinstance(value, list):
                for index, inner in enumerate(value):
                    walk(inner, f"{path}[{index}]")
            elif isinstance(value, str):
                self.assertLess(
                    len(value), 120, f"{path} looks like prose: {value[:80]!r}"
                )

        walk(self.get_shape())


class PublicPageTests(PublicFixture):
    def html(self):
        return self.client.get(reverse("public_trip", args=[self.token])).content.decode()

    def test_the_page_shows_the_structure(self):
        html = self.html()
        self.assertIn("Taos / Angel Fire", html)
        self.assertIn("Day 1", html)
        self.assertIn("Rancho de Chimayó", html)
        self.assertIn("New Mexican", html)
        self.assertIn("planned", html)

    def test_the_page_publishes_no_private_detail(self):
        html = self.html()
        for secret in (
            "James",          # Trip.name, Meal.why, Lodging.notes, Section.content
            "Regan",          # same
            "5305434791",     # Lodging.confirmation_number
            "GCH7JS",         # TransportLeg + Confirmation
            "DL 447",         # TransportLeg.service_number
            "555-0100",       # Contact.phone
            "fix Regan status",  # BookingTask.title
            "Arrival & Santa Fe Evening",  # Day.theme
            "Booked under",   # Trip.notes
            "Passport",       # Trip.notes
        ):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, html)

    def test_the_page_says_it_is_a_summary(self):
        self.assertIn("not published", self.html())


class LeakFinderTests(TestCase):
    """`find_leaks`, against shapes built to leak.

    The real-data sweep lives in `manage.py audit_public_leak` rather than here,
    because `manage.py test` builds an empty database and so cannot see the
    imported trips — where every actual leak has been. What is tested here is the
    detection logic, which is the part that can be tested honestly.
    """

    def test_a_clean_shape_finds_nothing(self):
        clean = Trip.objects.create(
            name="Private Name",
            destination="Somewhere",
            start_date=date(2027, 5, 1),
            end_date=date(2027, 5, 4),
        )
        names, numbers = trip_leak_finders(clean)
        self.assertEqual(find_leaks(public_trip(clean), names=names, numbers=numbers), [])

    def test_it_catches_a_confirmation_number(self):
        shape = {"destination": "x", "days": [], "leak": "5305434791"}
        findings = find_leaks(shape, numbers=["5305434791"])
        self.assertEqual(findings[0][0], "certain")
        self.assertIn("confirmation number", findings[0][1])

    def test_it_catches_a_flight_route(self):
        shape = {"summary": "Overnight flight — Pittsburgh (PIT) -> Frankfurt (FRA)"}
        severities = [severity for severity, _ in find_leaks(shape)]
        self.assertIn("certain", severities)

    def test_it_catches_a_long_numeric_code(self):
        findings = find_leaks({"x": "ref 123456789"})
        self.assertEqual(findings[0][0], "certain")
        self.assertIn("long numeric code", findings[0][1])

    def test_a_traveller_name_is_possible_not_certain(self):
        # The distinction the whole command hangs on: "St. James Hotel" is a
        # restaurant on a trip with a traveller called James, so a name match has
        # to be a prompt to look rather than a hard failure.
        findings = find_leaks({"name": "St. James Hotel, Cimarron"}, names=["James"])
        self.assertEqual(findings[0][0], "possible")

    def test_a_real_traveller_name_still_shows_up(self):
        findings = find_leaks({"summary": "Sara and Henry fly home"}, names=["Sara", "Henry"])
        self.assertEqual(len(findings), 2)
        self.assertTrue(all(severity == "possible" for severity, _ in findings))

    def test_very_short_name_words_are_ignored(self):
        # "Bo" and "Al" match inside ordinary words and would report on
        # everything.
        self.assertEqual(find_leaks({"name": "Baalbek"}, names=["Bo", "Al"]), [])

    def test_dates_do_not_defeat_the_patterns(self):
        # DjangoJSONEncoder, not str(): a bare str() would render
        # datetime.date(...) and the patterns would be matching the wrong text.
        findings = find_leaks({"start_date": "2027-03-01", "end_date": "2027-03-08"})
        self.assertEqual(findings, [])


class RealDataSweepTests(TestCase):
    """The sweep, skipped when there is no imported data to sweep.

    `manage.py audit_public_leak` is the version that has teeth in practice; this
    exists so the wiring is exercised and so a checkout with imported trips gets
    the check for free.
    """

    def test_every_live_trip_is_clean(self):
        trips = list(Trip.objects.live().prefetch_related(
            "days__meals", "days__sections", "travelers", "confirmations",
            "lodging", "transport",
        ))
        if not trips:
            self.skipTest("no imported trips in this database")
        for trip in trips:
            names, numbers = trip_leak_finders(trip)
            with self.subTest(trip=trip.pk):
                certain = [f for f in find_leaks(public_trip(trip), names, numbers)
                           if f[0] == "certain"]
                self.assertEqual(certain, [], f"trip {trip.pk} leaks {certain}")


class PublicQueryCountTests(PublicFixture):
    def test_a_long_trip_holds_a_fixed_query_count(self):
        # 25 days with meals and sections: the count must not move with the
        # length of the trip, which is the N+1 the prefetch comment warns about.
        for offset in range(2, 26):
            day = Day.objects.create(
                trip=self.trip,
                day_number=offset,
                date=self.trip.start_date + timedelta(days=offset - 1),
            )
            Meal.objects.create(day=day, name=f"Dinner {offset}", meal_type=Meal.MealType.DINNER)
            for index in range(2):
                Section.objects.create(
                    day=day, section_type=Section.Type.CALLOUT, order=index,
                    content={"tone": "info", "text": "x"},
                )
        # Four: the trip, then one query per prefetch level. Fixed regardless of
        # how long the trip is, which is the property the prefetch comment is
        # about — `len(...)` and `.all()`, never `.count()` per day.
        with self.assertNumQueries(4):
            response = self.client.get(reverse("public_trip", args=[self.token]))
        self.assertEqual(response.status_code, 200)


class PublicModelTests(TestCase):
    """The parts of the model the public view leans on."""

    def test_public_is_excluded_from_visible_to(self):
        # A token is not a grant. Holding one must not quietly grant app access.
        user = User.objects.create_user("ada", "ada@example.com", "pw-1234-abcd")
        trip = Trip.objects.create(
            name="T", start_date=date(2027, 1, 1), end_date=date(2027, 1, 5)
        )
        trip.enable_public()
        self.assertEqual(Trip.objects.visible_to(user).count(), 0)

    def test_a_comment_is_not_public(self):
        # Comments carry traveller names by definition; the public shape has no
        # key for them at all.
        user = User.objects.create_user("bo", "bo@example.com", "pw-1234-abcd")
        trip = Trip.objects.create(
            name="T", start_date=date(2027, 1, 1), end_date=date(2027, 1, 5)
        )
        Comment.objects.create(author=user, content_object=trip, body="Secret")
        blob = json.dumps(public_trip(trip), cls=DjangoJSONEncoder)
        self.assertNotIn("Secret", blob)
        self.assertNotIn("comment", blob.lower())

    def test_soft_deleted_trips_are_not_found_by_token(self):
        trip = Trip.objects.create(
            name="T", start_date=date(2027, 1, 1), end_date=date(2027, 1, 5)
        )
        token = trip.enable_public()
        self.assertEqual(Trip.objects.public(token).count(), 1)
        trip.soft_delete()
        self.assertEqual(Trip.objects.public(token).count(), 0)
        trip.restore()
        self.assertEqual(Trip.objects.public(token).count(), 1)

class PublicAdminTests(TestCase):
    """Minting and revoking from the admin, which is the only place it happens."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            "boss", "boss@example.com", "pw-1234-abcd"
        )
        self.client.force_login(self.admin)
        self.trip = Trip.objects.create(
            name="T", start_date=date(2027, 1, 1), end_date=date(2027, 1, 5)
        )

    def changelist(self):
        return reverse("admin:trips_trip_changelist")

    def act(self, action):
        return self.client.post(
            self.changelist(),
            {"action": action, "_selected_action": [str(self.trip.pk)]},
            follow=True,
        )

    def test_the_change_page_shows_the_link_once_created(self):
        self.trip.enable_public()
        response = self.client.get(
            reverse("admin:trips_trip_change", args=[self.trip.pk])
        )
        self.assertContains(response, str(self.trip.public_token))

    def test_the_change_page_says_when_a_trip_is_not_shared(self):
        response = self.client.get(
            reverse("admin:trips_trip_change", args=[self.trip.pk])
        )
        self.assertContains(response, "Not shared")

    def test_the_create_action_mints_a_token(self):
        self.act("create_public_links")
        self.trip.refresh_from_db()
        self.assertIsNotNone(self.trip.public_token)
        self.assertEqual(
            self.client.get(reverse("public_trip", args=[self.trip.public_token])).status_code,
            200,
        )

    def test_the_create_action_keeps_an_existing_token(self):
        # Otherwise selecting a mixed changelist silently breaks links.
        existing = self.trip.enable_public()
        self.act("create_public_links")
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.public_token, existing)

    def test_the_revoke_action_removes_the_page_only(self):
        token = self.trip.enable_public()
        self.act("revoke_public_links")
        self.trip.refresh_from_db()
        self.assertIsNone(self.trip.public_token)
        self.assertEqual(
            self.client.get(reverse("public_trip", args=[token])).status_code, 404
        )
        self.assertTrue(Trip.objects.filter(pk=self.trip.pk).exists())

    def test_revoke_says_so_when_there_was_nothing_to_revoke(self):
        response = self.act("revoke_public_links")
        self.assertContains(response, "None of the selected trips had a public link")

    def test_a_deleted_trip_is_not_given_a_link(self):
        # A token on a deleted trip would be unreachable anyway; minting one
        # would just be confusing.
        self.trip.soft_delete()
        self.act("create_public_links")
        self.trip.refresh_from_db()
        self.assertIsNone(self.trip.public_token)
