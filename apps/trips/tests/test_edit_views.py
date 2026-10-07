"""Tests for the trip editing views.

The permission rules get most of the attention here, because they are the part
that fails quietly: a view that lets someone edit a trip they should not would
still return 200 and still look correct, it would just hand one person another
person's confirmation numbers.
"""

from datetime import date, datetime, timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.trips.models import TripRole
from apps.trips.forms import TRIP_SUBSECTION_FORMSETS
from apps.trips.models import (
    BookingTask,
    Confirmation,
    Contact,
    Day,
    Lodging,
    Section,
    Traveler,
    TransportLeg,
    Trip,
    TripGrant,
    can_create_trip,
)
from apps.trips.views import _visible_capabilities

from apps.trips.tests.helpers import give

User = get_user_model()


def make_user(username, **kwargs):
    return User.objects.create_user(
        username, f"{username}@example.com", "pw-1234-abcd", **kwargs
    )


class TripEditingFixture(TestCase):
    def setUp(self):
        self.staff = make_user("root", is_staff=True, is_superuser=True)
        self.alice = make_user("alice")
        self.trip = Trip.objects.create(
            name="Taos",
            start_date=date(2026, 9, 12),
            end_date=date(2026, 9, 19),
        )

    def give(self, user, *roles, trip=None):
        return give(user, *roles, trip=trip, granted_by=self.staff)

    def own(self, user, trip=None):
        """Make ``user`` the trip's creator, as creating it in the app would."""
        trip = trip or self.trip
        trip.created_by = user
        trip.save(update_fields=["created_by"])
        return trip

    def valid_trip_payload(self, **overrides):
        data = {
            "name": "Taos",
            "destination": "New Mexico",
            "start_date": "2026-09-12",
            "end_date": "2026-09-19",
            "status": Trip.Status.STARTING,
        }
        # Management data first, then the caller's overrides, so a test that
        # passes row counts or fields is not silently overwritten by the
        # zero-row defaults.
        data.update(self.formsets_payload())
        data.update(overrides)
        return data

    def formsets_payload(self, counts=None, initial=None, **extra):
        """Management-form data for the trip edit page's five formsets.

        A real browser sends this; the edit view has nothing to work from
        without it, so a payload that omits it is not a payload the page could
        ever produce.

        ``counts`` maps a formset prefix to TOTAL_FORMS — how many rows are
        posted. ``initial`` maps a prefix to INITIAL_FORMS — how many of those
        rows already exist in the database.

        They are *not* the same number, and conflating them fails quietly: with
        INITIAL_FORMS too high, Django looks up each row's ``id``, finds no
        existing object, and skips the row as one that was already deleted. New
        rows are posted with an empty id and INITIAL_FORMS of 0.

        ``extra`` is merged in untouched, which is how row fields from
        :meth:`row` get in.
        """
        counts = counts or {}
        initial = initial or {}
        data = dict(extra)
        for key, _label, _cls in TRIP_SUBSECTION_FORMSETS:
            data.update(
                {
                    f"{key}-TOTAL_FORMS": counts.get(key, 0),
                    f"{key}-INITIAL_FORMS": initial.get(key, 0),
                    f"{key}-MIN_NUM_FORMS": 0,
                    f"{key}-MAX_NUM_FORMS": 1000,
                }
            )
        return data

    def row(self, key, index, **fields):
        """One formset row's fields, prefixed the way the page posts them."""
        return {f"{key}-{index}-{name}": value for name, value in fields.items()}


class TripCreateTests(TripEditingFixture):
    def test_a_creator_may_open_the_form(self):
        self.give(self.alice, Role.CREATOR)
        self.client.force_login(self.alice)
        response = self.client.get(reverse("trips:trip_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "New trip")

    def test_a_viewer_may_not_create(self):
        self.give(self.alice, TripRole.VIEWER, trip=self.trip)
        self.client.force_login(self.alice)
        self.assertEqual(
            self.client.get(reverse("trips:trip_create")).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                reverse("trips:trip_create"), self.valid_trip_payload()
            ).status_code,
            403,
        )
        self.assertEqual(Trip.objects.count(), 1)

    def test_an_anonymous_visitor_is_sent_to_login(self):
        response = self.client.get(reverse("trips:trip_create"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_creating_records_the_creator_and_grants_them_access(self):
        # The whole point of this test: without the grant, a creator would make
        # a trip that immediately vanishes from their own list.
        self.give(self.alice, Role.CREATOR)
        self.client.force_login(self.alice)
        self.client.post(reverse("trips:trip_create"), self.valid_trip_payload())

        trip = Trip.objects.get(name="Taos", pk=self.trip.pk + 1)
        self.assertEqual(trip.created_by, self.alice)
        self.assertIn(trip, Trip.objects.visible_to(self.alice))
        self.assertTrue(trip.can(self.alice, "edit"))

    def test_creating_redirects_to_the_new_trip(self):
        self.give(self.alice, Role.CREATOR)
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("trips:trip_create"), self.valid_trip_payload()
        )
        new = Trip.objects.exclude(pk=self.trip.pk).get()
        self.assertRedirects(
            response, reverse("trips:trip_detail", args=[new.pk])
        )

    def test_a_new_traveler_can_be_added_from_the_same_form(self):
        self.give(self.alice, Role.CREATOR)
        self.client.force_login(self.alice)
        self.client.post(
            reverse("trips:trip_create"),
            {**self.valid_trip_payload(), "new_traveler_name": "Ada Lovelace"},
        )
        new = Trip.objects.exclude(pk=self.trip.pk).get()
        self.assertEqual(
            [t.name for t in new.travelers.all()], ["Ada Lovelace"]
        )

    def test_a_blank_traveler_name_is_not_an_error(self):
        self.give(self.alice, Role.CREATOR)
        self.client.force_login(self.alice)
        before = Traveler.objects.count()
        response = self.client.post(
            reverse("trips:trip_create"),
            {**self.valid_trip_payload(), "new_traveler_name": "   "},
        )
        self.assertEqual(response.status_code, 302)
        # Compared against the starting count rather than zero: the fixture's
        # accounts each own a traveler row now (trips/signals.py), so the
        # assertion is that the blank submission adds none of its own.
        self.assertEqual(Traveler.objects.count(), before)

    def test_a_repeated_traveler_name_is_reused_not_duplicated(self):
        # Two rows called "Ada" would put one person on the roster twice and
        # make a split day naming one of them look like a split from the group.
        Traveler.objects.create(name="Ada Lovelace")
        self.give(self.alice, Role.CREATOR)
        self.client.force_login(self.alice)
        self.client.post(
            reverse("trips:trip_create"),
            {**self.valid_trip_payload(), "new_traveler_name": "Ada Lovelace"},
        )
        self.assertEqual(Traveler.objects.filter(name="Ada Lovelace").count(), 1)

    def test_an_end_date_before_the_start_is_rejected(self):
        self.give(self.alice, Role.CREATOR)
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("trips:trip_create"),
            self.valid_trip_payload(end_date="2026-09-01"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot be before the start date")
        self.assertEqual(Trip.objects.count(), 1)

    def test_the_status_form_preselects_starting(self):
        # A required select that opens blank makes every new trip a guess.
        self.give(self.alice, Role.CREATOR)
        self.client.force_login(self.alice)
        response = self.client.get(reverse("trips:trip_create"))
        self.assertContains(response, 'value="starting" selected')


class TripEditTests(TripEditingFixture):
    def test_an_editor_may_save_their_trip(self):
        self.give(self.alice, TripRole.EDITOR, trip=self.trip)
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("trips:trip_edit", args=[self.trip.pk]),
            self.valid_trip_payload(name="Taos, revised"),
        )
        self.assertRedirects(
            response, reverse("trips:trip_detail", args=[self.trip.pk])
        )
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.name, "Taos, revised")

    def test_a_commentor_may_not_edit(self):
        self.give(self.alice, TripRole.COMMENTOR, trip=self.trip)
        self.client.force_login(self.alice)
        # 403 not 404: she can already read the trip, so it is not a secret.
        self.assertEqual(
            self.client.get(
                reverse("trips:trip_edit", args=[self.trip.pk])
            ).status_code,
            403,
        )
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.name, "Taos")

    def test_a_user_with_no_grant_gets_404_not_403(self):
        # The distinction the module docstring is about: an invisible trip must
        # not be confirmed, even by its error code. Being able to create trips
        # says nothing about this one.
        self.give(self.alice, Role.CREATOR)
        self.client.force_login(self.alice)
        self.assertEqual(
            self.client.get(
                reverse("trips:trip_edit", args=[self.trip.pk])
            ).status_code,
            404,
        )

    def test_editing_does_not_change_the_creator(self):
        self.own(self.alice)
        self.give(self.alice, TripRole.EDITOR, trip=self.trip)
        self.client.force_login(self.alice)
        self.client.post(
            reverse("trips:trip_edit", args=[self.trip.pk]),
            self.valid_trip_payload(),
        )
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.created_by, self.alice)

    def test_a_traveler_can_be_added_while_editing(self):
        self.give(self.alice, TripRole.EDITOR, trip=self.trip)
        self.client.force_login(self.alice)
        self.client.post(
            reverse("trips:trip_edit", args=[self.trip.pk]),
            {**self.valid_trip_payload(), "new_traveler_name": "Bo"},
        )
        self.assertEqual(
            sorted(t.name for t in self.trip.travelers.all()), ["Bo"]
        )

    def test_a_deleted_trip_cannot_be_edited(self):
        self.give(self.alice, TripRole.EDITOR, trip=self.trip)
        self.trip.soft_delete()
        self.client.force_login(self.alice)
        self.assertEqual(
            self.client.get(
                reverse("trips:trip_edit", args=[self.trip.pk])
            ).status_code,
            404,
        )


class TripDeleteTests(TripEditingFixture):
    def test_the_creator_may_delete_their_trip(self):
        self.own(self.alice)
        self.give(self.alice, TripRole.EDITOR, trip=self.trip)
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("trips:trip_delete", args=[self.trip.pk])
        )
        self.assertRedirects(response, reverse("trips:trip_list"))
        self.trip.refresh_from_db()
        self.assertTrue(self.trip.is_deleted)

    def test_an_editor_who_did_not_create_the_trip_may_not_delete_it(self):
        self.give(self.alice, TripRole.EDITOR, trip=self.trip)
        self.client.force_login(self.alice)
        self.assertEqual(
            self.client.get(
                reverse("trips:trip_delete", args=[self.trip.pk])
            ).status_code,
            403,
        )
        self.trip.refresh_from_db()
        self.assertFalse(self.trip.is_deleted)

    def test_deleting_keeps_the_data(self):
        day = Day.objects.create(
            trip=self.trip, day_number=1, date=date(2026, 9, 12)
        )
        section = Section.objects.create(
            day=day, section_type=Section.Type.FREE_TEXT, content={}
        )
        self.own(self.alice)
        self.give(self.alice, TripRole.EDITOR, trip=self.trip)
        self.client.force_login(self.alice)
        self.client.post(reverse("trips:trip_delete", args=[self.trip.pk]))

        self.assertTrue(Trip.objects.filter(pk=self.trip.pk).exists())
        self.assertTrue(Day.objects.filter(pk=day.pk).exists())
        self.assertTrue(Section.objects.filter(pk=section.pk).exists())

    def test_get_only_confirms_and_never_deletes(self):
        self.own(self.alice)
        self.give(self.alice, TripRole.EDITOR, trip=self.trip)
        self.client.force_login(self.alice)
        response = self.client.get(
            reverse("trips:trip_delete", args=[self.trip.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.trip.refresh_from_db()
        self.assertFalse(self.trip.is_deleted)

    def test_staff_may_delete_an_admin_authored_trip(self):
        self.client.force_login(self.staff)
        self.client.post(reverse("trips:trip_delete", args=[self.trip.pk]))
        self.trip.refresh_from_db()
        self.assertTrue(self.trip.is_deleted)


class TripRestoreTests(TripEditingFixture):
    def test_staff_may_restore(self):
        self.trip.soft_delete()
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("trips:trip_restore", args=[self.trip.pk])
        )
        self.assertRedirects(
            response, reverse("trips:trip_detail", args=[self.trip.pk])
        )
        self.trip.refresh_from_db()
        self.assertFalse(self.trip.is_deleted)

    def test_a_creator_may_not_restore(self):
        # The trip is invisible to them, so there is no page to restore from.
        self.own(self.alice)
        self.give(self.alice, Role.CREATOR, trip=self.trip)
        self.trip.soft_delete()
        self.client.force_login(self.alice)
        self.assertEqual(
            self.client.post(
                reverse("trips:trip_restore", args=[self.trip.pk])
            ).status_code,
            404,
        )
        self.trip.refresh_from_db()
        self.assertTrue(self.trip.is_deleted)

    def test_get_does_not_restore(self):
        self.trip.soft_delete()
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("trips:trip_restore", args=[self.trip.pk])
        )
        self.assertRedirects(response, reverse("trips:trip_list"))
        self.trip.refresh_from_db()
        self.assertTrue(self.trip.is_deleted)


class TripListLinkTests(TripEditingFixture):
    """The list offers actions only to those allowed to take them."""

    def test_a_viewer_is_offered_no_edit_or_delete(self):
        self.give(self.alice, TripRole.VIEWER, trip=self.trip)
        self.client.force_login(self.alice)
        response = self.client.get(reverse("trips:trip_list"))
        self.assertNotContains(response, reverse("trips:trip_edit", args=[self.trip.pk]))
        self.assertNotContains(response, reverse("trips:trip_delete", args=[self.trip.pk]))

    def test_an_editor_is_offered_edit_but_not_delete(self):
        self.give(self.alice, TripRole.EDITOR, trip=self.trip)
        self.client.force_login(self.alice)
        response = self.client.get(reverse("trips:trip_list"))
        self.assertContains(response, reverse("trips:trip_edit", args=[self.trip.pk]))
        self.assertNotContains(response, reverse("trips:trip_delete", args=[self.trip.pk]))

    def test_the_creator_is_offered_both(self):
        self.own(self.alice)
        self.give(self.alice, Role.CREATOR, trip=self.trip)
        self.client.force_login(self.alice)
        response = self.client.get(reverse("trips:trip_list"))
        self.assertContains(response, reverse("trips:trip_edit", args=[self.trip.pk]))
        self.assertContains(response, reverse("trips:trip_delete", args=[self.trip.pk]))

    def test_only_a_creator_sees_the_new_trip_button(self):
        self.give(self.alice, TripRole.EDITOR, trip=self.trip)
        self.client.force_login(self.alice)
        self.assertNotContains(
            self.client.get(reverse("trips:trip_list")),
            reverse("trips:trip_create"),
        )

        self.give(self.alice, Role.CREATOR)
        self.assertContains(
            self.client.get(reverse("trips:trip_list")),
            reverse("trips:trip_create"),
        )

    def test_a_deleted_trip_leaves_the_list(self):
        self.give(self.alice, TripRole.VIEWER, trip=self.trip)
        self.trip.soft_delete()
        self.client.force_login(self.alice)
        self.assertNotContains(
            self.client.get(reverse("trips:trip_list")), "Taos"
        )


class ListCapabilityEquivalenceTests(TripEditingFixture):
    """The list computes capabilities without three queries a row.

    ``_visible_capabilities`` is a shortcut past ``Trip.capabilities_for``, so
    it is pinned against the real rule for every role. If the shortcut ever
    disagrees, this fails rather than the UI quietly offering the wrong button.
    """

    def _assert_matches(self, user, trip):
        shown = trip.list_capabilities
        for action in ("edit", "delete"):
            self.assertEqual(
                shown[action],
                trip.can(user, action),
                f"{user.username} {action} on {trip.name}",
            )

    def _check_every_role(self, trip):
        """Grant once, then vary only the grant's role.

        Re-granting per role would hit the unique_trip_grant constraint, and
        the role is the thing under test, not the grant.
        """
        grant = TripGrant.objects.create(trip=trip, user=self.alice, granted_by=self.staff)
        for role in TripRole.values:
            with self.subTest(role=role):
                grant.role = role
                grant.save(update_fields=["role"])
                # Re-attach per iteration: the shortcut writes the attribute,
                # and capabilities_for re-queries rather than caching, so
                # comparing fresh against fresh is the honest comparison.
                _visible_capabilities(self.alice, [trip])
                self._assert_matches(self.alice, trip)

    def test_every_role_on_an_owned_trip(self):
        self._check_every_role(self.own(self.alice))

    def test_every_role_on_a_trip_they_do_not_own(self):
        self._check_every_role(self.trip)

    def test_staff(self):
        self.client.force_login(self.staff)
        trips = list(Trip.objects.visible_to(self.staff))
        _visible_capabilities(self.staff, trips)
        self._assert_matches(self.staff, trips[0])


class CreateTripGuardTests(TripEditingFixture):
    def test_can_create_trip_is_still_the_gate(self):
        self.assertFalse(can_create_trip(self.alice))
        self.give(self.alice, TripRole.EDITOR, trip=self.trip)
        self.assertFalse(can_create_trip(self.alice))
        self.give(self.alice, Role.CREATOR)
        self.assertTrue(can_create_trip(self.alice))
        self.assertTrue(can_create_trip(self.staff))


class TripSubsectionFormsetTests(TripEditingFixture):
    """The trip-level lists on the edit page."""

    def edit(self, **overrides):
        self.client.force_login(self.alice)
        return self.client.post(
            reverse("trips:trip_edit", args=[self.trip.pk]),
            self.valid_trip_payload(**overrides),
        )

    def grant_editor(self):
        self.give(self.alice, TripRole.EDITOR, trip=self.trip)
        return self.alice

    def test_lodging_can_be_added(self):
        self.grant_editor()
        self.edit(
            **self.formsets_payload(
                {"lodging": 1},
                **self.row(
                    "lodging",
                    0,
                    name="El Rancho",
                    check_in="2026-09-12",
                    check_out="2026-09-15",
                    currency="USD",
                ),
            )
        )
        lodging = Lodging.objects.get()
        self.assertEqual(lodging.name, "El Rancho")
        self.assertEqual(lodging.trip, self.trip)
        self.assertEqual(lodging.nights, 3)

    def test_a_leg_is_stored_in_utc_from_local_times(self):
        self.grant_editor()
        self.edit(
            **self.formsets_payload(
                {"transport": 1},
                **self.row(
                    "transport",
                    0,
                    mode="train",
                    origin="Munich",
                    origin_timezone="Europe/Berlin",
                    departure_local="2027-09-25 10:00",
                    destination="Berlin",
                    destination_timezone="Europe/Berlin",
                    arrival_local="2027-09-25 14:00",
                ),
            )
        )
        leg = TransportLeg.objects.get()
        # 10:00 CEST is 08:00 UTC. If the conversion were skipped the row would
        # sit at 10:00 UTC and the detail page would show the wrong local time.
        self.assertEqual(
            leg.departure_at,
            datetime(2027, 9, 25, 8, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(leg.departure_local_str, "10:00 AM CEST")

    def test_a_leg_needs_a_timezone_to_convert_from(self):
        self.grant_editor()
        response = self.edit(
            **self.formsets_payload(
                {"transport": 1},
                **self.row(
                    "transport",
                    0,
                    mode="train",
                    origin="Munich",
                    departure_local="2027-09-25 10:00",
                    destination="Berlin",
                    arrival_local="2027-09-25 14:00",
                ),
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(TransportLeg.objects.exists())

    def test_an_earlier_arrival_is_rejected(self):
        self.grant_editor()
        self.edit(
            **self.formsets_payload(
                {"transport": 1},
                **self.row(
                    "transport",
                    0,
                    mode="train",
                    origin="Munich",
                    origin_timezone="Europe/Berlin",
                    departure_local="2027-09-25 14:00",
                    destination="Berlin",
                    destination_timezone="Europe/Berlin",
                    arrival_local="2027-09-25 10:00",
                ),
            )
        )
        self.assertFalse(TransportLeg.objects.exists())

    def test_a_confirmation_and_contact_can_be_added(self):
        self.grant_editor()
        self.edit(
            **self.formsets_payload(
                {"confirmations": 1, "contacts": 1},
                **self.row(
                    "confirmations",
                    0,
                    label="Hotel",
                    confirmation_number="ABC123",
                ),
                **self.row("contacts", 0, name="Front desk", phone="555-0100"),
            )
        )
        self.assertEqual(Confirmation.objects.get().confirmation_number, "ABC123")
        self.assertEqual(Contact.objects.get().name, "Front desk")

    def test_a_booking_task_can_be_added(self):
        self.grant_editor()
        self.edit(
            **self.formsets_payload(
                {"booking_tasks": 1},
                **self.row(
                    "booking_tasks",
                    0,
                    title="Book the Gulmarg flights",
                    priority=BookingTask.Priority.CRITICAL,
                    due_note="6+ months",
                ),
            )
        )
        task = BookingTask.objects.get()
        self.assertEqual(task.title, "Book the Gulmarg flights")
        # Both optional links stay empty rather than being required.
        self.assertIsNone(task.day)
        self.assertIsNone(task.confirmation)

    def test_a_task_cannot_point_at_another_trip_s_day(self):
        # The whole reason the choice querysets are narrowed.
        self.grant_editor()
        other = Trip.objects.create(
            name="Bavaria",
            start_date=date(2027, 9, 25),
            end_date=date(2027, 10, 5),
        )
        other_day = Day.objects.create(
            trip=other, day_number=1, date=date(2027, 9, 25)
        )
        self.edit(
            **self.formsets_payload(
                {"booking_tasks": 1},
                **self.row(
                    "booking_tasks",
                    0,
                    title="Book something",
                    priority=BookingTask.Priority.MEDIUM,
                    day=other_day.pk,
                ),
            )
        )
        self.assertFalse(BookingTask.objects.exists())

    def test_a_task_can_point_at_this_trip_s_day(self):
        self.grant_editor()
        day = Day.objects.create(
            trip=self.trip, day_number=1, date=date(2026, 9, 12)
        )
        self.edit(
            **self.formsets_payload(
                {"booking_tasks": 1},
                **self.row(
                    "booking_tasks",
                    0,
                    title="Decide on the day trip",
                    priority=BookingTask.Priority.HIGH,
                    day=day.pk,
                ),
            )
        )
        self.assertEqual(BookingTask.objects.get().day, day)

    def test_a_row_can_be_removed(self):
        self.grant_editor()
        lodging = Lodging.objects.create(
            trip=self.trip,
            name="El Rancho",
            check_in=date(2026, 9, 12),
            check_out=date(2026, 9, 15),
        )
        # The row has to be *valid* as well as deleted: a formset that fails
        # validation saves nothing at all, delete checkbox included. That is
        # the same all-or-nothing rule the view applies to the whole page.
        self.edit(
            **self.formsets_payload(
                {"lodging": 1},
                initial={"lodging": 1},
                **self.row(
                    "lodging",
                    0,
                    id=lodging.pk,
                    name=lodging.name,
                    check_in="2026-09-12",
                    check_out="2026-09-15",
                    DELETE="on",
                ),
            )
        )
        self.assertFalse(Lodging.objects.exists())

    def test_a_blank_extra_row_is_not_saved(self):
        # extra=1 always renders an empty row. Saving it untouched must not
        # create a row of NULLs, and must not error either.
        self.grant_editor()
        self.edit(
            **self.formsets_payload(
                {
                    "lodging": 1,
                    "contacts": 1,
                    "confirmations": 1,
                    "transport": 1,
                    "booking_tasks": 1,
                },
            )
        )
        self.assertEqual(Lodging.objects.count(), 0)
        self.assertEqual(TransportLeg.objects.count(), 0)
        self.assertEqual(Confirmation.objects.count(), 0)
        self.assertEqual(Contact.objects.count(), 0)
        self.assertEqual(BookingTask.objects.count(), 0)

    def test_one_bad_row_writes_nothing_at_all(self):
        # The all-or-nothing rule. A lodging row that fails validation must not
        # let the confirmation beside it through, or the trip ends up half
        # edited and the error message describes a form already scrolled past.
        self.grant_editor()
        self.edit(
            **self.formsets_payload(
                {"confirmations": 1, "lodging": 1},
                **self.row(
                    "confirmations", 0, label="Hotel", confirmation_number="X1"
                ),
                # check_out before check_in.
                **self.row(
                    "lodging",
                    0,
                    name="El Rancho",
                    check_in="2026-09-15",
                    check_out="2026-09-12",
                ),
            )
        )
        self.assertFalse(Confirmation.objects.exists())
        self.assertFalse(Lodging.objects.exists())

    def test_every_formset_reports_its_own_errors_in_one_pass(self):
        # all() short-circuits, which would hide the second error until the
        # first was fixed. Both must show at once.
        self.grant_editor()
        response = self.edit(
            **self.formsets_payload(
                {"lodging": 1, "confirmations": 1},
                **self.row(
                    "lodging",
                    0,
                    name="El Rancho",
                    check_in="2026-09-15",
                    check_out="2026-09-12",
                ),
                # A confirmation with no number at all.
                **self.row("confirmations", 0, label="Hotel"),
            )
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Check-out cannot be before check-in.", body)
        self.assertIn("This field is required.", body)

    def test_the_trip_itself_is_not_saved_when_a_row_fails(self):
        self.grant_editor()
        self.edit(
            name="Renamed anyway",
            **self.formsets_payload(
                {"lodging": 1},
                **self.row(
                    "lodging",
                    0,
                    name="El Rancho",
                    check_in="2026-09-15",
                    check_out="2026-09-12",
                ),
            )
        )
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.name, "Taos")

    def test_an_editor_may_not_reach_the_page_at_all(self):
        self.give(self.alice, TripRole.VIEWER, trip=self.trip)
        self.client.force_login(self.alice)
        self.assertEqual(
            self.client.get(
                reverse("trips:trip_edit", args=[self.trip.pk])
            ).status_code,
            403,
        )

    def test_the_page_renders_every_formset(self):
        self.grant_editor()
        self.client.force_login(self.alice)
        response = self.client.get(
            reverse("trips:trip_edit", args=[self.trip.pk])
        )
        body = response.content.decode()
        for key, _label, _cls in TRIP_SUBSECTION_FORMSETS:
            self.assertIn(f"{key}-TOTAL_FORMS", body)


class TransportLegFormsetTests(TripSubsectionFormsetTests):
    """The transport formset specifically: zones, and local-time round trips."""

    def edit_leg(self, **leg):
        self.grant_editor()
        return self.edit(
            **self.formsets_payload(
                {"transport": 1},
                **self.row("transport", 0, **leg),
            )
        )

    def test_an_invalid_zone_name_is_rejected(self):
        # The app's zone input is free text rather than a dropdown of all 486
        # names, so the check cannot be "is this one of the listed options" any
        # more. It has to actually resolve the name, or a typo would silently
        # render in UTC.
        self.edit_leg(
            mode="train",
            origin="Munich",
            origin_timezone="Europe/Munchen",
            departure_local="2027-09-25 10:00",
            destination="Berlin",
            destination_timezone="Europe/Berlin",
            arrival_local="2027-09-25 14:00",
        )
        self.assertFalse(TransportLeg.objects.exists())

    def test_a_lowercase_zone_name_is_rejected(self):
        # ZoneInfo is case-sensitive, so "europe/berlin" is not a valid IANA
        # name. The admin's dropdown rejects it too, and it should: quietly
        # case-folding here would make the app and the admin disagree about
        # which names exist, which is the one thing the shared mixin exists to
        # prevent.
        self.edit_leg(
            mode="train",
            origin="Munich",
            origin_timezone="europe/berlin",
            departure_local="2027-09-25 10:00",
            destination="Berlin",
            destination_timezone="Europe/Berlin",
            arrival_local="2027-09-25 14:00",
        )
        self.assertFalse(TransportLeg.objects.exists())

    def test_surrounding_whitespace_in_a_zone_is_ignored(self):
        self.edit_leg(
            mode="train",
            origin="Munich",
            origin_timezone="  Europe/Berlin  ",
            departure_local="2027-09-25 10:00",
            destination="Berlin",
            destination_timezone="Europe/Berlin",
            arrival_local="2027-09-25 14:00",
        )
        self.assertEqual(
            TransportLeg.objects.get().origin_timezone, "Europe/Berlin"
        )

    def test_a_time_carrying_its_own_offset_is_trusted(self):
        # The same rule the admin form has: an explicit offset wins over the
        # zone, so it is never re-converted.
        self.edit_leg(
            mode="plane",
            origin="JFK",
            origin_timezone="America/New_York",
            departure_local="2026-01-15T18:00:00+00:00",
            destination="DEN",
            destination_timezone="America/Denver",
            arrival_local="2026-01-15T21:00:00+00:00",
        )
        self.assertEqual(
            TransportLeg.objects.get().departure_at,
            datetime(2026, 1, 15, 18, 0, tzinfo=timezone.utc),
        )

    def test_an_existing_leg_reopens_with_its_local_times_filled_in(self):
        # Regression guard. TransportLegForm grew a second __init__ while the
        # datalist attrs were being added, and Python kept the last one — which
        # silently dropped seed_local_time_initial. Every existing leg would
        # have opened with blank times and re-saving would have failed.
        self.grant_editor()
        leg = TransportLeg.objects.create(
            trip=self.trip,
            mode=TransportLeg.Mode.PLANE,
            origin="JFK",
            destination="DEN",
            origin_timezone="America/New_York",
            destination_timezone="America/Denver",
            departure_at=datetime(2026, 1, 15, 23, 0, tzinfo=timezone.utc),
            arrival_at=datetime(2026, 1, 16, 2, 30, tzinfo=timezone.utc),
        )
        self.client.force_login(self.alice)
        body = self.client.get(
            reverse("trips:trip_edit", args=[self.trip.pk])
        ).content.decode()
        # 23:00 UTC is 6:00 PM in New York.
        self.assertIn('value="2026-01-15 18:00"', body)
        # 02:30 UTC the next day is 7:30 PM the previous day in Denver.
        self.assertIn('value="2026-01-15 19:30"', body)

    def test_the_zone_control_is_not_a_full_dropdown(self):
        # 486 zone <option>s per control, one per row, made this page 358kb.
        # Guard the size so a convenient-looking select does not come back.
        self.grant_editor()
        TransportLeg.objects.create(
            trip=self.trip,
            mode=TransportLeg.Mode.PLANE,
            origin="A",
            destination="B",
            origin_timezone="UTC",
            destination_timezone="UTC",
            departure_at=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
            arrival_at=datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc),
        )
        self.client.force_login(self.alice)
        body = self.client.get(
            reverse("trips:trip_edit", args=[self.trip.pk])
        ).content.decode()
        self.assertNotIn("Antarctica/Troll", body)
        self.assertIn("<datalist", body)
