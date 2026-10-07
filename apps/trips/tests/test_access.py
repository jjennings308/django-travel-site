"""Tests for the access layer.

The rules under test are the ones that would fail *quietly* if they were
wrong. A view that leaked a trip would still render; it would just show the
wrong person someone's confirmation numbers. So most of what is pinned here is
negative: that someone with a role but no grant, a grant but no role, or a grant
to a *different* trip, can see nothing at all.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, UserRole
from apps.trips.models import TripRole
from apps.trips.models import Day, Section, Traveler, Trip, TripGrant, can_create_trip

from apps.trips.tests.helpers import give

User = get_user_model()


def make_user(username, **kwargs):
    return User.objects.create_user(username, f"{username}@example.com", "pw-1234-abcd", **kwargs)


def make_trip(name, **kwargs):
    kwargs.setdefault("start_date", date(2027, 9, 17))
    kwargs.setdefault("end_date", date(2027, 10, 3))
    return Trip.objects.create(name=name, **kwargs)


class AccessFixture(TestCase):
    def setUp(self):
        self.admin = make_user("admin", is_staff=True, is_superuser=True)
        self.alice = make_user("alice")
        self.europe = make_trip("Europe 2027")
        self.taos = make_trip("Taos 2026", start_date=date(2026, 9, 12), end_date=date(2026, 9, 20))

    def give(self, user, *roles, trip=None):
        return give(user, *roles, trip=trip, granted_by=self.admin)

    def url(self, trip):
        return reverse("trips:trip_detail", args=[trip.pk])


class GrantRoleTests(AccessFixture):
    """The role lives on the grant, so it is per trip."""

    def test_a_grant_defaults_to_viewer(self):
        TripGrant.objects.create(trip=self.europe, user=self.alice, granted_by=self.admin)
        self.assertEqual(self.europe.capabilities_for(self.alice), {"view"})

    def test_roles_differ_per_trip(self):
        # The reason the role moved: one person can edit their own trip and
        # only read somebody else's.
        self.give(self.alice, TripRole.EDITOR, trip=self.europe)
        self.give(self.alice, TripRole.VIEWER, trip=self.taos)
        self.assertEqual(self.europe.capabilities_for(self.alice), {"view", "comment", "edit"})
        self.assertEqual(self.taos.capabilities_for(self.alice), {"view"})

    def test_one_grant_per_trip_and_user(self):
        # Changing what someone may do is changing the role, not adding a row.
        self.give(self.alice, TripRole.VIEWER, trip=self.europe)
        with self.assertRaises(Exception):
            TripGrant.objects.create(
                trip=self.europe, user=self.alice, role=TripRole.EDITOR, granted_by=self.admin
            )

    def test_changing_the_role_changes_the_capabilities(self):
        self.give(self.alice, TripRole.VIEWER, trip=self.europe)
        TripGrant.objects.filter(trip=self.europe, user=self.alice).update(role=TripRole.EDITOR)
        self.assertEqual(self.europe.capabilities_for(self.alice), {"view", "comment", "edit"})

    def test_creator_is_the_only_app_wide_role(self):
        self.assertEqual(Role.values, [Role.CREATOR])

    def test_duplicate_creator_rows_are_rejected(self):
        self.give(self.alice, Role.CREATOR)
        with self.assertRaises(Exception):
            UserRole.objects.create(user=self.alice, role=Role.CREATOR, granted_by=self.admin)


class CapabilityTests(AccessFixture):
    def test_viewer_can_only_view(self):
        self.give(self.alice, TripRole.VIEWER, trip=self.europe)
        self.assertEqual(self.europe.capabilities_for(self.alice), {"view"})

    def test_commentor_can_view_and_comment(self):
        self.give(self.alice, TripRole.COMMENTOR, trip=self.europe)
        self.assertEqual(self.europe.capabilities_for(self.alice), {"view", "comment"})

    def test_editor_can_view_comment_and_edit(self):
        self.give(self.alice, TripRole.EDITOR, trip=self.europe)
        self.assertEqual(self.europe.capabilities_for(self.alice), {"view", "comment", "edit"})

    def test_creator_with_an_editor_grant_gets_everything_except_manage(self):
        # manage is staff-only; see the docstring. Being a creator adds nothing
        # on an existing trip beyond its grant.
        self.give(self.alice, Role.CREATOR, trip=self.europe)
        self.assertEqual(
            self.europe.capabilities_for(self.alice), {"view", "comment", "edit"}
        )

    def test_superuser_bypasses_grant_and_role(self):
        self.assertEqual(
            self.europe.capabilities_for(self.admin),
            {"view", "comment", "edit", "delete", "restore", "manage"},
        )

    def test_creator_without_a_grant_gets_nothing(self):
        # The important negative: "may create trips" says nothing about a trip
        # somebody else made and nobody has shared.
        self.give(self.alice, Role.CREATOR)
        self.assertEqual(self.europe.capabilities_for(self.alice), set())

    def test_a_grant_is_scoped_to_its_own_trip(self):
        self.give(self.alice, TripRole.EDITOR, trip=self.europe)
        self.assertEqual(self.europe.capabilities_for(self.alice), {"view", "comment", "edit"})
        self.assertEqual(self.taos.capabilities_for(self.alice), set())

    def test_deactivating_an_account_revokes_access_immediately(self):
        # Not "at their next login" — the queryset checks is_active, so
        # deactivating someone takes effect without touching a session.
        self.give(self.alice, TripRole.EDITOR, trip=self.europe)
        self.assertTrue(self.europe.can(self.alice, "edit"))
        self.alice.is_active = False
        self.alice.save()
        self.assertEqual(self.europe.capabilities_for(self.alice), set())

    def test_anonymous_gets_nothing(self):
        self.assertEqual(self.europe.capabilities_for(AnonymousUser()), set())

    def test_can_is_the_boolean_form_of_capabilities(self):
        self.give(self.alice, TripRole.VIEWER, trip=self.europe)
        self.assertTrue(self.europe.can(self.alice, "view"))
        self.assertFalse(self.europe.can(self.alice, "edit"))

    def test_access_is_independent_of_trip_status(self):
        # A trip still being planned is fully readable by someone granted it.
        # Gating reads on status would hide a trip from the very people
        # building it.
        self.europe.status = Trip.Status.STARTING
        self.europe.save()
        self.give(self.alice, TripRole.EDITOR, trip=self.europe)
        self.assertEqual(
            self.europe.capabilities_for(self.alice), {"view", "comment", "edit"}
        )

    def test_access_is_independent_of_the_traveler_roster(self):
        # "Regan is on the trip" and "Regan can read the trip" are different
        # facts. Being a traveler grants nothing.
        regan = make_user("regan")
        self.europe.travelers.create(name="Regan")
        self.assertEqual(self.europe.capabilities_for(regan), set())


class VisibleToTests(AccessFixture):
    def test_granted_trip_is_visible(self):
        self.give(self.alice, TripRole.VIEWER, trip=self.europe)
        self.assertEqual(list(Trip.objects.visible_to(self.alice)), [self.europe])

    def test_ungranted_trip_is_hidden(self):
        self.give(self.alice, TripRole.VIEWER, trip=self.europe)
        self.assertNotIn(self.taos, Trip.objects.visible_to(self.alice))

    def test_creator_without_grant_sees_nothing(self):
        self.give(self.alice, Role.CREATOR)
        self.assertEqual(list(Trip.objects.visible_to(self.alice)), [])

    def test_staff_sees_every_trip(self):
        self.assertEqual(set(Trip.objects.visible_to(self.admin)), {self.europe, self.taos})

    def test_anonymous_sees_nothing(self):
        self.assertEqual(list(Trip.objects.visible_to(None)), [])
        self.assertEqual(list(Trip.objects.visible_to(AnonymousUser())), [])

    def test_other_users_grants_do_not_duplicate_the_trip(self):
        # Several grants on one trip join several rows; distinct() keeps the
        # reader's list to one entry per trip.
        self.give(self.alice, TripRole.VIEWER, trip=self.europe)
        self.give(self.bob, TripRole.EDITOR, trip=self.europe)
        self.assertEqual(len(Trip.objects.visible_to(self.alice)), 1)

    def test_a_grant_held_by_a_different_user_does_not_leak_access(self):
        self.give(self.alice, Role.CREATOR)
        self.give(self.bob, TripRole.VIEWER, trip=self.europe)
        self.assertEqual(list(Trip.objects.visible_to(self.alice)), [])
        self.assertEqual(list(Trip.objects.visible_to(self.bob)), [self.europe])

    def setUp(self):
        super().setUp()
        self.bob = make_user("bob")


class CanCreateTripTests(AccessFixture):
    def test_creator_may_create(self):
        self.give(self.alice, Role.CREATOR)
        self.assertTrue(can_create_trip(self.alice))

    def test_an_editor_grant_does_not_allow_creating(self):
        self.give(self.alice, TripRole.EDITOR, trip=self.europe)
        self.assertFalse(can_create_trip(self.alice))

    def test_staff_may_create(self):
        self.assertTrue(can_create_trip(self.admin))

    def test_anonymous_may_not_create(self):
        self.assertFalse(can_create_trip(AnonymousUser()))


class TripListViewTests(AccessFixture):
    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("trips:trip_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_a_granted_trip_is_listed(self):
        self.give(self.alice, TripRole.VIEWER, trip=self.europe)
        self.client.force_login(self.alice)
        response = self.client.get(reverse("trips:trip_list"))
        self.assertContains(response, "Europe 2027")

    def test_an_ungranted_trip_is_not_listed(self):
        self.give(self.alice, TripRole.VIEWER, trip=self.europe)
        self.client.force_login(self.alice)
        response = self.client.get(reverse("trips:trip_list"))
        self.assertNotContains(response, "Taos 2026")

    def test_draft_and_ready_are_labelled(self):
        self.europe.status = Trip.Status.READY_TO_GO
        self.europe.save()
        self.give(self.alice, TripRole.VIEWER, trip=self.europe)
        self.client.force_login(self.alice)
        response = self.client.get(reverse("trips:trip_list"))
        self.assertContains(response, "Ready")

    def test_a_staff_user_sees_every_trip(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("trips:trip_list"))
        self.assertContains(response, "Europe 2027")
        self.assertContains(response, "Taos 2026")

    def test_the_card_names_the_travellers_and_counts_the_days(self):
        # The list used to be a table of name/status/dates only; the cards
        # surface who is going and how much itinerary there is, so both are
        # asserted here rather than left as an untested rendering change.
        ada = Traveler.objects.create(name="Ada Lovelace")
        self.europe.travelers.add(ada)
        Day.objects.create(trip=self.europe, day_number=1, date=date(2027, 9, 17))
        Day.objects.create(trip=self.europe, day_number=2, date=date(2027, 9, 18))
        self.give(self.alice, TripRole.VIEWER, trip=self.europe)
        self.client.force_login(self.alice)
        response = self.client.get(reverse("trips:trip_list"))
        self.assertContains(response, "Ada Lovelace")
        self.assertContains(response, "Days")
        listed = [t for t in response.context["trips"] if t.pk == self.europe.pk]
        self.assertEqual(listed[0].days_count, 2)

    def test_a_trip_with_no_days_still_renders_its_card(self):
        # days_count is a Count annotation: zero rows, but the card must not
        # treat that as absent information.
        self.give(self.alice, TripRole.VIEWER, trip=self.europe)
        self.client.force_login(self.alice)
        response = self.client.get(reverse("trips:trip_list"))
        self.assertContains(response, "Days")
        self.assertContains(response, "None outstanding")

    def test_logout_requires_post(self):
        # Django 5+ made GET logout a no-op; a <a href> would silently fail.
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)


class TripDetailAccessTests(AccessFixture):
    """The detail view is the second place a trip is reachable, so it has to
    hold the same line as the list.

    A 404 rather than a 403 is the point: on a trip carrying confirmation
    numbers, "403" already tells a stranger that the trip exists.
    """

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(self.url(self.europe))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_a_granted_trip_is_readable(self):
        self.give(self.alice, TripRole.VIEWER, trip=self.europe)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(self.url(self.europe)).status_code, 200)

    def test_an_ungranted_trip_is_404_not_403(self):
        self.give(self.alice, TripRole.VIEWER, trip=self.europe)
        self.client.force_login(self.alice)
        response = self.client.get(self.url(self.taos))
        self.assertEqual(response.status_code, 404)

    def test_a_grant_on_another_trip_is_still_404(self):
        self.give(self.alice, TripRole.EDITOR, trip=self.taos)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(self.url(self.europe)).status_code, 404)

    def test_a_creator_without_a_grant_is_still_404(self):
        self.give(self.alice, Role.CREATOR)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(self.url(self.europe)).status_code, 404)

    def test_a_draft_trip_is_readable(self):
        # status is a label, not a gate: the people building a trip have to be
        # able to read it.
        self.europe.status = Trip.Status.STARTING
        self.europe.save()
        self.give(self.alice, TripRole.VIEWER, trip=self.europe)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(self.url(self.europe)).status_code, 200)

    def test_a_traveler_without_a_grant_cannot_read_the_trip(self):
        from apps.trips.models import Traveler

        # Being on the trip is not being able to read it: Traveler and User are
        # different models, and only TripGrant grants access.
        self.europe.travelers.add(Traveler.objects.create(name="Regan"))
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(self.url(self.europe)).status_code, 404)

    def test_an_inactive_user_cannot_read_a_granted_trip(self):
        self.give(self.alice, TripRole.VIEWER, trip=self.europe)
        self.alice.is_active = False
        self.alice.save()
        self.client.force_login(self.alice)

        # The redirect is Django's, not ours: ModelBackend.get_user() refuses an
        # inactive user, so request.user is already AnonymousUser by the time
        # login_required runs. Asserting 404 here would be asserting a behaviour
        # this app does not control.
        denied = self.client.get(self.url(self.europe))
        self.assertEqual(denied.status_code, 302)
        self.assertIn("/accounts/login/", denied["Location"])

        # Our own guard is what protects the non-session paths — a user object
        # handed to the queryset or to Trip.can directly, with no session and so
        # no ModelBackend check.
        self.assertEqual(list(Trip.objects.visible_to(self.alice)), [])
        self.assertFalse(self.europe.can(self.alice, "read"))

    def test_staff_can_read_a_trip_with_no_grant(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url(self.europe)).status_code, 200)

    def test_a_missing_trip_is_404(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("trips:trip_detail", args=[999999])).status_code, 404)


class OwnershipDeleteTests(AccessFixture):
    """``created_by`` ownership and the ``delete`` capability.

    Deleting is soft, but the *permission* to delete is not a lesser thing: it
    is the only capability that destroys content, so the rule is ownership plus
    edit-class access rather than either alone.
    """

    def test_the_creator_may_delete_their_own_trip(self):
        self.europe.created_by = self.alice
        self.europe.save(update_fields=["created_by"])
        self.give(self.alice, Role.CREATOR, trip=self.europe)
        self.assertTrue(self.europe.can(self.alice, "delete"))

    def test_an_editor_who_did_not_create_the_trip_may_not_delete_it(self):
        # Being handed someone else's trip to edit is not being handed
        # permission to remove it.
        self.give(self.alice, TripRole.EDITOR, trip=self.europe)
        self.assertFalse(self.europe.can(self.alice, "delete"))

    def test_the_creator_needs_edit_class_access_to_delete(self):
        # Being the creator is necessary but not sufficient: an owner who has
        # been demoted to viewer is a viewer first.
        self.europe.created_by = self.alice
        self.europe.save(update_fields=["created_by"])
        self.give(self.alice, TripRole.VIEWER, trip=self.europe)
        self.assertFalse(self.europe.can(self.alice, "delete"))
        self.assertTrue(self.europe.can(self.alice, "view"))

    def test_an_admin_authored_trip_is_staff_only(self):
        # created_by is blank for anything curated in the admin, and there is
        # no user whose ownership claim could apply.
        self.assertIsNone(self.europe.created_by)
        self.give(self.alice, Role.CREATOR, trip=self.europe)
        self.assertFalse(self.europe.can(self.alice, "delete"))
        self.assertTrue(self.europe.can(self.admin, "delete"))

    def test_restore_is_staff_only(self):
        self.europe.created_by = self.alice
        self.europe.save(update_fields=["created_by"])
        self.give(self.alice, Role.CREATOR, trip=self.europe)
        self.assertFalse(self.europe.can(self.alice, "restore"))
        self.assertTrue(self.europe.can(self.admin, "restore"))

    def test_manage_is_still_staff_only(self):
        # Changing who can reach a trip is a separate axis from deleting it.
        self.give(self.alice, Role.CREATOR, trip=self.europe)
        self.assertFalse(self.europe.can(self.alice, "manage"))


class SoftDeleteTests(AccessFixture):
    def test_soft_delete_hides_the_trip_but_keeps_the_row(self):
        day = Day.objects.create(
            trip=self.taos, day_number=1, date=date(2026, 9, 12)
        )
        Section.objects.create(
            day=day, section_type=Section.Type.FREE_TEXT, content={}
        )
        pk = self.taos.pk

        self.taos.soft_delete()

        self.assertTrue(self.taos.is_deleted)
        self.assertEqual(list(Trip.objects.live()), [self.europe])
        self.assertEqual(list(Trip.objects.deleted()), [self.taos])
        # Nothing was destroyed, which is the entire point.
        self.assertTrue(Trip.objects.filter(pk=pk).exists())
        self.assertEqual(Section.objects.filter(day__trip_id=pk).count(), 1)

    def test_soft_delete_is_idempotent(self):
        self.taos.soft_delete()
        first = self.taos.deleted_at
        self.taos.soft_delete()
        self.taos.refresh_from_db()
        self.assertEqual(self.taos.deleted_at, first)

    def test_restore_puts_it_back(self):
        self.taos.soft_delete()
        self.taos.restore()
        self.taos.refresh_from_db()
        self.assertFalse(self.taos.is_deleted)
        self.assertIsNone(self.taos.deleted_at)
        self.assertIn(self.taos, Trip.objects.live())

    def test_restore_on_a_live_trip_is_a_no_op(self):
        self.taos.restore()
        self.taos.refresh_from_db()
        self.assertIsNone(self.taos.deleted_at)

    def test_a_deleted_trip_is_hidden_from_everyone_including_staff(self):
        self.taos.soft_delete()
        self.assertNotIn(self.taos, Trip.objects.visible_to(self.admin))
        self.give(self.alice, TripRole.VIEWER, trip=self.taos)
        self.assertNotIn(self.taos, Trip.objects.visible_to(self.alice))

    def test_a_deleted_trip_detail_page_is_404(self):
        self.taos.soft_delete()
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(self.url(self.taos)).status_code, 404
        )

    def test_a_deleted_trip_leaves_the_list(self):
        self.taos.soft_delete()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("trips:trip_list"))
        self.assertNotContains(response, self.taos.name)
        self.assertContains(response, self.europe.name)
