"""Tests for the travel profile: preferences, documents, rewards programs.

The rule under test is "self and staff only". There is no pk in the profile
URL, so the page cannot be pointed at somebody else; what is left to pin is
that the data never leaks *sideways* — onto a trip page a co-traveler reads,
into the public view, or into a ``__str__`` that the admin log and formset
summaries print.
"""

import io
from datetime import date

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.trips.models import TripRole
from apps.trips.models import RewardsMembership, Traveler, Trip, TripGrant
from apps.trips.public import public_trip

User = get_user_model()

URL = reverse("trips:traveler_profile")


def make_user(username, **kwargs):
    return User.objects.create_user(
        username, f"{username}@example.com", "pw-1234-abcd", **kwargs
    )


def profile_payload(rows=1, initial=0, **overrides):
    """A full profile POST. ``rows``/``initial`` are TOTAL/INITIAL_FORMS."""
    data = {
        "seat_preference": "aisle",
        "cabin_preference": "",
        "bed_preference": "",
        "meal_preference": "",
        "home_airport": "pit",
        "dietary_notes": "",
        "mobility_notes": "",
        "known_traveler_number": "",
        "redress_number": "",
        "passport_country": "us",
        "passport_number": "",
        "passport_expires": "",
        "memberships-TOTAL_FORMS": str(rows),
        "memberships-INITIAL_FORMS": str(initial),
        "memberships-MIN_NUM_FORMS": "0",
        "memberships-MAX_NUM_FORMS": "1000",
    }
    for i in range(rows):
        data.update(
            {
                f"memberships-{i}-kind": "airline",
                f"memberships-{i}-program": "",
                f"memberships-{i}-member_number": "",
                f"memberships-{i}-tier": "",
                f"memberships-{i}-expires": "",
                f"memberships-{i}-notes": "",
            }
        )
    data.update(overrides)
    return data


class ProfilePageTests(TestCase):
    def setUp(self):
        self.alice = make_user("alice", first_name="Alice", last_name="Ames")
        self.traveler = Traveler.objects.get(user=self.alice)
        self.client.force_login(self.alice)

    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_an_account_with_no_traveler_is_a_404(self):
        Traveler.objects.filter(user=self.alice).update(user=None)
        self.assertEqual(self.client.get(URL).status_code, 404)

    def test_the_page_shows_the_persons_own_data(self):
        self.traveler.known_traveler_number = "TT1234567"
        self.traveler.save()
        response = self.client.get(URL)
        self.assertContains(response, "Alice Ames")
        self.assertContains(response, "TT1234567")

    def test_saving_updates_the_profile_and_normalises_codes(self):
        response = self.client.post(
            URL, profile_payload(known_traveler_number="TT1", passport_expires="2031-05-01")
        )
        self.assertRedirects(response, URL)
        self.traveler.refresh_from_db()
        self.assertEqual(self.traveler.seat_preference, "aisle")
        self.assertEqual(self.traveler.home_airport, "PIT")
        self.assertEqual(self.traveler.passport_country, "US")
        self.assertEqual(self.traveler.passport_expires, date(2031, 5, 1))

    def test_a_posted_name_is_ignored(self):
        self.client.post(URL, profile_payload(name="Somebody Else"))
        self.traveler.refresh_from_db()
        self.assertEqual(self.traveler.name, "Alice Ames")

    def test_the_untouched_blank_program_row_is_not_saved(self):
        self.client.post(URL, profile_payload())
        self.assertFalse(RewardsMembership.objects.exists())

    def test_a_program_can_be_added_edited_and_removed(self):
        self.client.post(
            URL,
            profile_payload(
                **{
                    "memberships-0-program": "Delta SkyMiles",
                    "memberships-0-member_number": "9988776655",
                }
            ),
        )
        membership = RewardsMembership.objects.get(traveler=self.traveler)
        self.assertEqual(membership.member_number, "9988776655")

        self.client.post(
            URL,
            profile_payload(
                rows=2,
                initial=1,
                **{
                    "memberships-0-id": str(membership.pk),
                    "memberships-0-program": "Delta SkyMiles",
                    "memberships-0-member_number": "9988776655",
                    "memberships-0-tier": "Gold",
                },
            ),
        )
        membership.refresh_from_db()
        self.assertEqual(membership.tier, "Gold")

        self.client.post(
            URL,
            profile_payload(
                rows=2,
                initial=1,
                **{
                    "memberships-0-id": str(membership.pk),
                    "memberships-0-program": "Delta SkyMiles",
                    "memberships-0-member_number": "9988776655",
                    "memberships-0-DELETE": "on",
                },
            ),
        )
        self.assertFalse(RewardsMembership.objects.exists())

    def test_a_bad_program_row_rolls_back_the_profile_too(self):
        response = self.client.post(
            URL,
            profile_payload(
                seat_preference="window",
                **{"memberships-0-program": "Marriott Bonvoy"},  # no number
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.traveler.refresh_from_db()
        self.assertEqual(self.traveler.seat_preference, "")
        self.assertFalse(RewardsMembership.objects.exists())

    def test_the_same_program_twice_is_a_form_error_not_a_500(self):
        response = self.client.post(
            URL,
            profile_payload(
                rows=2,
                **{
                    "memberships-0-program": "Delta SkyMiles",
                    "memberships-0-member_number": "1",
                    "memberships-1-program": "Delta SkyMiles",
                    "memberships-1-member_number": "2",
                },
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(RewardsMembership.objects.exists())

    def test_the_formset_summary_does_not_show_the_member_number(self):
        RewardsMembership.objects.create(
            traveler=self.traveler, program="Hilton Honors", member_number="55443322"
        )
        response = self.client.get(URL)
        # The number is in its input (it is the person's own page), but the
        # one-line row summary is __str__, which must not carry it.
        self.assertContains(response, "55443322", count=1)


class PrivacyRuleTests(TestCase):
    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.staff = make_user("staff", is_staff=True)
        self.traveler = Traveler.objects.get(user=self.alice)

    def test_self_and_staff_only(self):
        self.assertTrue(self.traveler.is_private_to(self.alice))
        self.assertTrue(self.traveler.is_private_to(self.staff))
        self.assertFalse(self.traveler.is_private_to(self.bob))

    def test_an_inactive_account_sees_nothing(self):
        self.alice.is_active = False
        self.alice.save()
        self.assertFalse(self.traveler.is_private_to(self.alice))

    def test_an_accountless_traveler_is_private_to_staff_only(self):
        loner = Traveler.objects.create(name="No Account")
        self.assertTrue(loner.is_private_to(self.staff))
        self.assertFalse(loner.is_private_to(self.alice))

    def test_str_never_includes_the_member_number(self):
        membership = RewardsMembership.objects.create(
            traveler=self.traveler,
            program="Delta SkyMiles",
            member_number="9988776655",
            tier="Gold",
        )
        self.assertEqual(str(membership), "Delta SkyMiles (Gold)")
        self.assertEqual(membership.masked_number, "••••6655")


class NoSidewaysLeakTests(TestCase):
    """A co-traveler reading the trip sees names, never the private data."""

    SECRETS = ("9988776655", "TT1234567", "X12345678")

    def setUp(self):
        admin = make_user("admin", is_staff=True)
        self.alice = make_user("alice", first_name="Alice", last_name="Ames")
        self.bob = make_user("bob")
        traveler = Traveler.objects.get(user=self.alice)
        traveler.known_traveler_number = "TT1234567"
        traveler.passport_number = "X12345678"
        traveler.save()
        RewardsMembership.objects.create(
            traveler=traveler, program="Delta SkyMiles", member_number="9988776655"
        )
        self.trip = Trip.objects.create(
            name="Shared",
            start_date=date(2026, 9, 12),
            end_date=date(2026, 9, 19),
        )
        self.trip.travelers.add(traveler, Traveler.objects.get(user=self.bob))
        TripGrant.objects.create(
            trip=self.trip, user=self.bob, role=TripRole.EDITOR, granted_by=admin
        )

    def test_the_trip_page_shows_the_name_not_the_numbers(self):
        self.client.force_login(self.bob)
        response = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        self.assertContains(response, "Alice Ames")
        for secret in self.SECRETS:
            self.assertNotContains(response, secret)

    def test_the_public_view_carries_none_of_it(self):
        self.trip.enable_public()
        shape = repr(public_trip(self.trip))
        for secret in self.SECRETS:
            self.assertNotIn(secret, shape)


class DedupeMembershipTests(TestCase):
    def setUp(self):
        self.donor = Traveler.objects.create(name="Debbie", redress_number="R1")
        self.keeper = Traveler.objects.create(name="Debbie Fowler")
        RewardsMembership.objects.create(
            traveler=self.donor, program="Delta SkyMiles", member_number="D-1"
        )
        RewardsMembership.objects.create(
            traveler=self.donor, program="Hilton Honors", member_number="D-2"
        )
        RewardsMembership.objects.create(
            traveler=self.keeper, program="Hilton Honors", member_number="K-2"
        )

    def test_programs_move_to_the_keeper_and_the_keeper_wins_a_clash(self):
        out = io.StringIO()
        call_command("dedupe_travelers", apply=True, stdout=out)
        self.assertIn("kept Debbie Fowler's programs: Hilton Honors", out.getvalue())
        numbers = dict(
            self.keeper.memberships.values_list("program", "member_number")
        )
        self.assertEqual(numbers, {"Delta SkyMiles": "D-1", "Hilton Honors": "K-2"})
        self.keeper.refresh_from_db()
        self.assertEqual(self.keeper.redress_number, "R1")
