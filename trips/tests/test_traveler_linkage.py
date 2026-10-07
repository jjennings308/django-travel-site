"""Tests for the traveler/account link.

The rule under test is one-way and fails quietly when it breaks the wrong
way: an account that does not become a traveler is invisible until somebody
tries to find the person on a roster, and a link attached to the *wrong*
traveler would hand one person's login to another person's trips. So both
directions, the ambiguity escapes and the admin action's refusal paths are
pinned here rather than left to be discovered on a real roster.

The account is never an access axis: creating one grants no role and no trip
grant, and the tests below say so explicitly (see also
``test_access.test_a_traveler_without_a_grant_cannot_read_the_trip``).
"""

import io
import tempfile
from contextlib import redirect_stdout
from datetime import date

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserRole
from trips.models import Day, Trip, TripGrant, Traveler
from trips.tests.test_docx_import import build_document, run_import

User = get_user_model()


def make_trip(**kwargs):
    defaults = {
        "name": "Test Trip",
        "start_date": date(2026, 9, 12),
        "end_date": date(2026, 9, 19),
    }
    defaults.update(kwargs)
    return Trip.objects.create(**defaults)


def make_user(username, **kwargs):
    return User.objects.create_user(username, f"{username}@example.com", "pw-1234-abcd", **kwargs)


class AccountIsTravelerTests(TestCase):
    """Saving an account must produce exactly one correctly named traveler."""

    def test_an_account_with_no_full_name_gets_a_traveler_named_for_it(self):
        user = make_user("alice")
        traveler = Traveler.objects.get(user=user)
        self.assertEqual(traveler.name, "alice")

    def test_an_account_prefers_its_full_name_for_the_traveler(self):
        user = make_user("bo", first_name="Bo", last_name="Clark")
        traveler = Traveler.objects.get(user=user)
        self.assertEqual(traveler.name, "Bo Clark")

    def test_a_superuser_is_a_traveler_too(self):
        User.objects.create_superuser("root", "root@example.com", "pw")
        self.assertTrue(Traveler.objects.filter(name="root").exists())

    def test_an_account_links_a_traveler_the_roster_already_has(self):
        existing = Traveler.objects.create(name="Debbie Fowler")
        user = make_user("debbie", first_name="Debbie", last_name="Fowler")
        existing.refresh_from_db()
        self.assertEqual(existing.user, user)
        self.assertEqual(Traveler.objects.filter(name="Debbie Fowler").count(), 1)

    def test_creating_a_traveler_links_an_account_that_already_exists(self):
        user = make_user("bo", first_name="Bo", last_name="Clark")
        Traveler.objects.filter(user=user).delete()
        traveler = Traveler.objects.create(name="Bo Clark")
        self.assertEqual(traveler.user, user)

    def test_an_ambiguous_name_is_left_unlinked_rather_than_guessed(self):
        Traveler.objects.create(name="Sam")
        Traveler.objects.create(name="Sam")
        user = make_user("sam", first_name="Sam")
        self.assertFalse(Traveler.objects.filter(user=user).exists())

    def test_a_second_traveler_with_a_linked_name_does_not_steal_the_link(self):
        user = make_user("bo", first_name="Bo", last_name="Clark")
        linked = Traveler.objects.get(user=user)
        other = Traveler.objects.create(name="Bo Clark")
        other.refresh_from_db()
        self.assertIsNone(other.user)
        linked.refresh_from_db()
        self.assertEqual(linked.user, user)

    def test_renaming_an_account_neither_renames_nor_unlinks_the_traveler(self):
        # The link is identity, not a live name mirror: a traveler row is
        # pointed at by trips and rosters, and renaming it behind them would
        # change what every roster renders.
        user = make_user("bo", first_name="Bo", last_name="Clark")
        traveler = Traveler.objects.get(user=user)
        user.first_name = "Beau"
        user.save()
        traveler.refresh_from_db()
        self.assertEqual(traveler.name, "Bo Clark")
        self.assertEqual(traveler.user, user)

    def test_deleting_an_account_keeps_the_traveler_and_its_information(self):
        user = make_user("bo", first_name="Bo", last_name="Clark")
        traveler = Traveler.objects.get(user=user)
        traveler.dietary_notes = "no shellfish"
        traveler.save(update_fields=["dietary_notes"])
        user.delete()
        traveler.refresh_from_db()
        self.assertIsNone(traveler.user)
        self.assertEqual(traveler.name, "Bo Clark")
        self.assertEqual(traveler.dietary_notes, "no shellfish")


class CreateAccountActionTests(TestCase):
    """The option to make an account *for* a traveler, without losing it."""

    def setUp(self):
        self.staff = User.objects.create_superuser("root", "root@example.com", "pw")
        self.client.force_login(self.staff)
        self.trip = make_trip()
        self.traveler = Traveler.objects.create(name="Debbie Fowler")
        self.trip.travelers.add(self.traveler)

    def _act(self, *pks):
        return self.client.post(
            reverse("admin:trips_traveler_changelist"),
            {"action": "create_accounts", "_selected_action": list(pks)},
            follow=True,
        )

    def test_the_action_links_the_existing_row_and_leaves_it_in_place(self):
        self._act(self.traveler.pk)
        user = User.objects.get(username="debbie")
        self.traveler.refresh_from_db()
        self.assertEqual(self.traveler.user, user)
        self.assertEqual(user.first_name, "Debbie")
        self.assertEqual(user.last_name, "Fowler")
        self.assertEqual(user.get_full_name(), self.traveler.name)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(list(self.trip.travelers.all()), [self.traveler])

    def test_the_action_grants_no_role_and_no_trip_access(self):
        # Access stays a separate, deliberate act; the account is only an
        # identity. A traveler link granting trips would reinstate exactly
        # the axis the access layer was built to keep apart.
        self._act(self.traveler.pk)
        user = User.objects.get(username="debbie")
        self.assertEqual(UserRole.objects.filter(user=user).count(), 0)
        self.assertEqual(TripGrant.objects.filter(user=user).count(), 0)

    def test_a_traveler_that_already_has_an_account_is_skipped(self):
        make_user("debbie", first_name="Debbie", last_name="Fowler")
        before = User.objects.count()
        response = self._act(self.traveler.pk)
        self.assertEqual(User.objects.count(), before)
        self.assertContains(response, "already has the account")

    def test_two_travelers_with_one_name_are_refused_until_merged(self):
        Traveler.objects.create(name="Debbie Fowler")
        response = self._act(self.traveler.pk)
        self.assertFalse(User.objects.filter(username="debbie").exists())
        self.assertContains(response, "merge them with dedupe_travelers")

    def test_a_taken_username_falls_back_to_the_whole_name(self):
        make_user("debbie")
        self._act(self.traveler.pk)
        user = User.objects.get(username="debbiefowler")
        self.traveler.refresh_from_db()
        self.assertEqual(self.traveler.user, user)

    def test_a_row_the_signal_cannot_match_is_reconciled_not_duplicated(self):
        # Two spaces in the name mean get_full_name() will not equal the row
        # exactly, so the signal builds its own row; the action must end with
        # this row linked and no orphan beside it. The fixture's traveler goes
        # first — with it present the action would rightly refuse as ambiguous.
        self.traveler.delete()
        odd = Traveler.objects.create(name="Debbie  Fowler")
        self.trip.travelers.add(odd)
        self._act(odd.pk)
        odd.refresh_from_db()
        self.assertIsNotNone(odd.user_id)
        self.assertEqual(Traveler.objects.filter(name__contains="Fowler").count(), 1)

    def test_a_name_with_no_words_is_refused(self):
        blankish = Traveler.objects.create(name="...")
        response = self._act(blankish.pk)
        self.assertFalse(User.objects.filter(username="user").exists())
        self.assertContains(response, "no name to derive an account from")


class DedupeTravelersTests(TestCase):
    """The merge that makes a person one row again."""

    def setUp(self):
        self.trip = make_trip()
        self.day = Day.objects.create(
            trip=self.trip, day_number=1, date=date(2026, 9, 12)
        )
        self.keeper = Traveler.objects.create(name="Debbie Fowler")
        self.donor = Traveler.objects.create(name="Debbie")
        self.donor.dietary_notes = "no shellfish"
        self.donor.home_airport = "BWI"
        self.donor.passport_country = "US"
        self.donor.save(
            update_fields=["dietary_notes", "home_airport", "passport_country"]
        )
        self.keeper.passport_country = "CA"
        self.keeper.save(update_fields=["passport_country"])
        self.trip.travelers.add(self.donor)
        self.day.travelers.add(self.donor)

    def _run(self, apply=False):
        out = io.StringIO()
        call_command("dedupe_travelers", apply=apply, stdout=out)
        return out.getvalue()

    def test_a_dry_run_writes_nothing(self):
        output = self._run()
        self.assertIn("Would merge 1", output)
        self.assertTrue(Traveler.objects.filter(pk=self.donor.pk).exists())
        self.assertEqual(list(self.trip.travelers.all()), [self.donor])

    def test_apply_merges_trips_days_and_missing_details(self):
        self._run(apply=True)
        self.assertFalse(Traveler.objects.filter(pk=self.donor.pk).exists())
        self.keeper.refresh_from_db()
        self.assertEqual(self.keeper.dietary_notes, "no shellfish")
        self.assertEqual(self.keeper.home_airport, "BWI")
        # A conflict keeps the keeper's value rather than silently overwriting it.
        self.assertEqual(self.keeper.passport_country, "CA")
        self.assertEqual(list(self.trip.travelers.all()), [self.keeper])
        self.assertEqual(list(self.day.travelers.all()), [self.keeper])

    def test_apply_moves_the_account_when_only_the_donor_has_one(self):
        user = make_user("debs")
        Traveler.objects.filter(user=user).delete()
        Traveler.objects.filter(pk=self.donor.pk).update(user=user)
        self._run(apply=True)
        self.keeper.refresh_from_db()
        self.assertEqual(self.keeper.user_id, user.pk)
        self.assertEqual(Traveler.objects.filter(user=user).count(), 1)

    def test_an_ambiguous_pair_is_skipped_with_a_warning(self):
        Traveler.objects.create(name="Debbie Smith")
        output = self._run(apply=True)
        self.assertIn("skipped", output)
        self.assertEqual(
            sorted(Traveler.objects.values_list("name", flat=True)),
            ["Debbie", "Debbie Fowler", "Debbie Smith"],
        )

    def test_a_pair_where_both_rows_have_an_account_is_skipped(self):
        first = make_user("debs")
        second = make_user("debs2")
        Traveler.objects.filter(user__in=[first, second]).delete()
        Traveler.objects.filter(pk=self.donor.pk).update(user=first)
        Traveler.objects.filter(pk=self.keeper.pk).update(user=second)
        output = self._run(apply=True)
        self.assertIn("both rows have an account", output)
        self.assertTrue(Traveler.objects.filter(pk=self.donor.pk).exists())

    def test_a_second_run_merges_nothing(self):
        self._run(apply=True)
        self.assertEqual(self._run(apply=True), "Nothing to merge.\n")


class ImportRosterReuseTests(TestCase):
    """A re-import must reuse the roster, not grow it a row at a time."""

    def test_a_replace_reimport_does_not_duplicate_travelers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = build_document(tmp)
            run_import(path, apply=True)
            self.assertEqual(Traveler.objects.filter(name="Ada Lovelace").count(), 1)
            run_import(path, apply=True, replace=True)
            self.assertEqual(Traveler.objects.filter(name="Ada Lovelace").count(), 1)
            self.assertEqual(Traveler.objects.count(), 2)
