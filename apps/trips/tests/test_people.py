"""The People page and invite links (site roadmap R1)."""
import re
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.notifications.models import Notification
from apps.trips import people
from apps.trips.models import Traveler, Trip, TripGrant, TripInvite, TripRole

User = get_user_model()


def make_user(username, **kwargs):
    return User.objects.create_user(username, f"{username}@example.com", "pw-1234-abcd", **kwargs)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", SITE_URL="https://example.test")
class PeopleFixture(TestCase):
    def setUp(self):
        self.owner = make_user("owner", first_name="Olive", last_name="Owner")
        self.ed = make_user("ed", first_name="Ed", last_name="Itor")
        self.carl = make_user("carl")
        self.vera = make_user("vera")
        self.stranger = make_user("stranger")
        self.trip = Trip.objects.create(name="Rome", start_date=date(2027, 5, 1), end_date=date(2027, 5, 8),
                                        created_by=self.owner)
        self.grant(self.owner, TripRole.EDITOR, by=self.owner)
        self.grant(self.ed, TripRole.EDITOR)
        self.grant(self.carl, TripRole.COMMENTOR)
        self.grant(self.vera, TripRole.VIEWER)
        self.url = reverse("trips:trip_people", args=[self.trip.pk])
        mail.outbox = []

    def grant(self, user, role, by=None):
        return TripGrant.objects.create(trip=self.trip, user=user, role=role, granted_by=by or self.owner)

    def g(self, user):
        return TripGrant.objects.get(trip=self.trip, user=user)

    def post(self, user, **data):
        self.client.force_login(user)
        return self.client.post(self.url, data)

    def invite_link(self):
        return re.search(r"https://example\.test(/trips/invite/[^/\s]+/)", mail.outbox[-1].body).group(1)


class PageTests(PeopleFixture):
    def test_everyone_on_the_trip_sees_the_people(self):
        for user in (self.vera, self.carl, self.ed):
            self.client.force_login(user)
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, 200)
            for name in ("Olive Owner", "Ed Itor", "carl", "vera"):
                self.assertContains(response, name)
            self.assertContains(response, "Created the trip")

    def test_viewers_and_commentors_cannot_invite_or_change_roles(self):
        for user in (self.vera, self.carl):
            self.client.force_login(user)
            response = self.client.get(self.url)
            self.assertNotContains(response, "Invite someone")
            self.assertNotContains(response, 'name="role"')
            self.assertContains(response, "Leave this trip")
            self.assertEqual(self.post(user, action="invite", email="x@example.com", role="viewer").status_code, 403)
            self.assertEqual(self.post(user, action="role", grant=self.g(self.vera).pk, role="editor").status_code, 403)
            self.assertEqual(self.post(user, action="remove", grant=self.g(self.ed).pk).status_code, 403)

    def test_editor_sees_the_controls(self):
        self.client.force_login(self.ed)
        response = self.client.get(self.url)
        self.assertContains(response, "Invite someone")
        self.assertContains(response, f'id="role-{self.g(self.vera).pk}"')
        self.assertNotContains(response, f'id="role-{self.g(self.owner).pk}"')  # the creator's role is fixed

    def test_no_grant_is_a_404(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, {"action": "invite", "email": "a@b.co", "role": "viewer"}).status_code, 404)

    def test_trip_page_and_edit_page_link_to_people(self):
        self.client.force_login(self.vera)
        self.assertContains(self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])), self.url)
        self.client.force_login(self.ed)
        self.assertContains(self.client.get(reverse("trips:trip_edit", args=[self.trip.pk])), self.url)


class RoleAndRemoveTests(PeopleFixture):
    def test_editor_changes_a_role(self):
        self.post(self.ed, action="role", grant=self.g(self.vera).pk, role="commentor")
        self.assertEqual(self.g(self.vera).role, TripRole.COMMENTOR)

    def test_creator_cannot_be_demoted_or_removed(self):
        owner_grant = self.g(self.owner)
        self.assertEqual(self.post(self.ed, action="role", grant=owner_grant.pk, role="viewer").status_code, 403)
        self.assertEqual(self.post(self.ed, action="remove", grant=owner_grant.pk).status_code, 403)
        self.assertEqual(self.post(self.owner, action="remove", grant=owner_grant.pk).status_code, 403)
        self.assertEqual(self.g(self.owner).role, TripRole.EDITOR)

    def test_cannot_grant_above_own_role(self):
        # Only editors may act, and editor is the top role, so check the rule itself.
        self.assertFalse(people.can_set(self.trip, TripRole.COMMENTOR, self.g(self.vera), TripRole.EDITOR))
        self.assertTrue(people.can_set(self.trip, TripRole.COMMENTOR, self.g(self.vera), TripRole.COMMENTOR))
        self.assertFalse(people.can_set(self.trip, TripRole.COMMENTOR, self.g(self.ed), TripRole.VIEWER))
        self.assertEqual([v for v, _ in people.roles_up_to(TripRole.COMMENTOR)], ["viewer", "commentor"])
        self.assertFalse(people.can_set(self.trip, TripRole.EDITOR, self.g(self.vera), "owner"))

    def test_editor_removes_someone(self):
        self.post(self.ed, action="remove", grant=self.g(self.carl).pk)
        self.assertFalse(TripGrant.objects.filter(trip=self.trip, user=self.carl).exists())

    def test_anyone_can_leave(self):
        response = self.post(self.vera, action="remove", grant=self.g(self.vera).pk)
        self.assertRedirects(response, reverse("trips:trip_list"))
        self.assertFalse(TripGrant.objects.filter(trip=self.trip, user=self.vera).exists())

    def test_another_trips_grant_is_a_404(self):
        other = Trip.objects.create(name="Paris", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        foreign = TripGrant.objects.create(trip=other, user=self.vera, role=TripRole.VIEWER)
        self.assertEqual(self.post(self.ed, action="remove", grant=foreign.pk).status_code, 404)


class InviteTests(PeopleFixture):
    def test_existing_account_is_granted_at_once_with_a_notification(self):
        response = self.post(self.ed, action="invite", email="  STRANGER@example.com ", role="commentor")
        self.assertRedirects(response, self.url)
        self.assertEqual(self.g(self.stranger).role, TripRole.COMMENTOR)
        self.assertEqual(self.g(self.stranger).granted_by, self.ed)
        self.assertFalse(TripInvite.objects.exists())
        self.assertTrue(Notification.objects.filter(user=self.stranger,
                                                    notification_type__name="trip_access_granted").exists())

    def test_existing_account_keeps_a_higher_role(self):
        self.post(self.ed, action="invite", email="carl@example.com", role="viewer")
        self.assertEqual(self.g(self.carl).role, TripRole.COMMENTOR)

    def test_new_address_gets_an_invite_email(self):
        self.post(self.ed, action="invite", email="New.Person@Example.com", role="viewer")
        invite = TripInvite.objects.get()
        self.assertEqual((invite.email, invite.role, invite.invited_by), ("new.person@example.com", "viewer", self.ed))
        self.assertEqual(invite.state, TripInvite.State.OPEN)
        self.assertAlmostEqual(invite.expires_at, timezone.now() + timedelta(days=14), delta=timedelta(minutes=1))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["new.person@example.com"])
        self.assertIn("Ed Itor invited you", mail.outbox[0].body)
        self.assertIn(f"/trips/invite/{invite.token}/", mail.outbox[0].body)

    def test_the_message_is_the_same_either_way(self):
        def message(email):
            response = self.client.post(self.url, {"action": "invite", "email": email, "role": "viewer"}, follow=True)
            return [str(m) for m in response.context["messages"]][0]
        self.client.force_login(self.ed)
        self.assertEqual(message("stranger@example.com").replace("stranger", "X"),
                         message("nobody@example.com").replace("nobody", "X"))

    def test_inviting_again_renews_the_one_open_invite(self):
        self.post(self.ed, action="invite", email="new@example.com", role="viewer")
        first = TripInvite.objects.get().token
        self.post(self.ed, action="invite", email="new@example.com", role="editor")
        invite = TripInvite.objects.get()
        self.assertNotEqual(invite.token, first)
        self.assertEqual(invite.role, "editor")

    def test_resend_and_cancel(self):
        self.post(self.ed, action="invite", email="new@example.com", role="viewer")
        invite = TripInvite.objects.get()
        old = invite.token
        self.post(self.ed, action="resend", invite=invite.pk)
        invite.refresh_from_db()
        self.assertNotEqual(invite.token, old)
        self.assertEqual(len(mail.outbox), 2)
        self.post(self.ed, action="cancel", invite=invite.pk)
        invite.refresh_from_db()
        self.assertEqual(invite.state, TripInvite.State.CANCELLED)

    def test_open_invites_are_listed_for_editors_only(self):
        self.post(self.ed, action="invite", email="new@example.com", role="viewer")
        self.client.force_login(self.ed)
        self.assertContains(self.client.get(self.url), "new@example.com")
        self.client.force_login(self.vera)
        self.assertNotContains(self.client.get(self.url), "new@example.com")

    def test_daily_limit(self):
        for n in range(people.INVITES_PER_DAY):
            TripInvite.objects.create(trip=self.trip, email=f"p{n}@example.com", invited_by=self.ed)
        self.post(self.ed, action="invite", email="one-more@example.com", role="viewer")
        self.assertFalse(TripInvite.objects.filter(email="one-more@example.com").exists())
        self.assertEqual(mail.outbox, [])

    def test_mail_failure_keeps_the_invite(self):
        with mock.patch("apps.trips.people.EmailMessage.send", side_effect=OSError("smtp down")), \
                self.assertLogs("apps.trips.people", "ERROR"):
            response = self.post(self.ed, action="invite", email="new@example.com", role="viewer")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(TripInvite.objects.filter(email="new@example.com").exists())


class AcceptTests(PeopleFixture):
    def setUp(self):
        super().setUp()
        self.post(self.ed, action="invite", email="friend@example.com", role="commentor")
        self.invite = TripInvite.objects.get()
        self.link = reverse("trips:invite_accept", args=[self.invite.token])
        self.client.logout()

    def test_signed_out_offers_login_and_register_coming_back(self):
        response = self.client.get(self.link)
        self.assertContains(response, "Rome")
        self.assertContains(response, "Ed Itor invited you")
        self.assertContains(response, "next=%2Ftrips%2Finvite%2F")
        self.assertContains(response, "email=friend%40example.com")

    def test_signed_in_join(self):
        self.client.force_login(self.stranger)
        self.assertContains(self.client.get(self.link), "Join trip")
        response = self.client.post(self.link, {"travelling": "1"})
        self.assertRedirects(response, reverse("trips:trip_detail", args=[self.trip.pk]))
        self.assertEqual(self.g(self.stranger).role, TripRole.COMMENTOR)
        self.assertEqual(self.g(self.stranger).granted_by, self.ed)
        self.invite.refresh_from_db()
        self.assertEqual((self.invite.state, self.invite.accepted_by), (TripInvite.State.ACCEPTED, self.stranger))
        self.assertIn(Traveler.objects.get(user=self.stranger), self.trip.travelers.all())
        # The inviter hears about it; the person who clicked Join isn't told they were added.
        self.assertTrue(Notification.objects.filter(user=self.ed, notification_type__name="trip_invite_accepted").exists())
        self.assertFalse(Notification.objects.filter(user=self.stranger).exists())

    def test_not_travelling(self):
        self.client.force_login(self.stranger)
        self.client.post(self.link, {})
        self.assertTrue(TripGrant.objects.filter(trip=self.trip, user=self.stranger).exists())
        self.assertFalse(self.trip.travelers.filter(user=self.stranger).exists())

    def test_raises_but_never_lowers(self):
        self.client.force_login(self.vera)
        self.client.post(self.link, {})
        self.assertEqual(self.g(self.vera).role, TripRole.COMMENTOR)
        invite = TripInvite.objects.create(trip=self.trip, email="other@example.com", role="viewer", invited_by=self.ed)
        self.client.post(reverse("trips:invite_accept", args=[invite.token]), {})
        self.assertEqual(self.g(self.vera).role, TripRole.COMMENTOR)

    def test_used_once(self):
        self.client.force_login(self.stranger)
        self.client.post(self.link, {})
        self.client.force_login(self.vera)
        response = self.client.post(self.link, {})
        self.assertEqual(response.status_code, 410)
        self.assertContains(response, "already been used", status_code=410)
        self.assertEqual(self.g(self.vera).role, TripRole.VIEWER)

    def test_expired(self):
        TripInvite.objects.filter(pk=self.invite.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.client.force_login(self.stranger)
        response = self.client.post(self.link, {})
        self.assertContains(response, "expired", status_code=410)
        self.assertFalse(TripGrant.objects.filter(trip=self.trip, user=self.stranger).exists())

    def test_cancelled(self):
        TripInvite.objects.filter(pk=self.invite.pk).update(revoked_at=timezone.now())
        self.client.force_login(self.stranger)
        response = self.client.post(self.link, {})
        self.assertContains(response, "cancelled", status_code=410)
        self.assertFalse(TripGrant.objects.filter(trip=self.trip, user=self.stranger).exists())

    def test_resent_link_replaces_the_old_one(self):
        self.client.force_login(self.ed)
        self.client.post(self.url, {"action": "resend", "invite": self.invite.pk})
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.link).status_code, 404)

    def test_deleted_trip(self):
        Trip.objects.filter(pk=self.trip.pk).update(deleted_at=timezone.now())
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.link).status_code, 404)

    def test_after_registering(self):
        """Register from the invite → verify by email → log in → back to the invite → join."""
        signed_out = self.client.get(self.link)
        register_url = signed_out.context["register_url"]
        form = self.client.get(register_url)
        self.assertEqual(form.context["form"].initial["email"], "friend@example.com")
        self.assertContains(form, 'name="next"')
        data = {"username": "friend", "email": "friend@example.com", "first_name": "Fran", "last_name": "Friend",
                "password1": "a-Long-pass-9876", "password2": "a-Long-pass-9876", "next": self.link,
                "agree_to_terms": "on", "terms_accepted": "on"}
        response = self.client.post(reverse("register"), data)
        self.assertEqual(response.status_code, 302)
        verify = re.search(r"https?://[^/\s]+(/[^\s]*verify-email/[^\s]+)", mail.outbox[-1].body).group(1)
        self.assertIn("next=", verify)
        response = self.client.get(verify)
        self.assertEqual(response.url, f"{reverse('login')}?next={self.link.replace('/', '%2F')}")
        response = self.client.post(response.url, {"username": "friend", "password": "a-Long-pass-9876"})
        self.assertRedirects(response, self.link, fetch_redirect_response=False)
        self.client.post(self.link, {"travelling": "1"})
        friend = User.objects.get(username="friend")
        self.assertEqual(self.g(friend).role, TripRole.COMMENTOR)

    def test_register_ignores_an_offsite_next(self):
        response = self.client.get(reverse("register") + "?next=https://evil.example/")
        self.assertNotContains(response, "evil.example")
