"""Sign-in and password pages.

Moved from the itinerary project's trips tests when its trips app was merged
in (work plan, Phase 1); they now exercise this site's accounts URLs and
templates. Every auth page is mounted, so every one of them has to render.
"""

import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class AuthFixture(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            "alice", "alice@example.com", "pw-1234-abcd"
        )


class LoginTests(AuthFixture):
    def test_login_page_renders(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Login")

    def test_valid_credentials_log_in_and_land_on_the_dashboard(self):
        response = self.client.post(
            reverse("login"), {"username": "alice", "password": "pw-1234-abcd"}
        )
        self.assertRedirects(response, reverse("pages:dashboard"))

    def test_next_wins_over_the_default_landing_page(self):
        target = reverse("trips:trip_list")
        response = self.client.post(
            f"{reverse('login')}?next={target}",
            {"username": "alice", "password": "pw-1234-abcd"},
        )
        self.assertRedirects(response, target)

    def test_wrong_password_does_not_log_in(self):
        response = self.client.post(reverse("login"), {"username": "alice", "password": "nope"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_an_inactive_account_cannot_log_in(self):
        self.alice.is_active = False
        self.alice.save()
        self.client.post(reverse("login"), {"username": "alice", "password": "pw-1234-abcd"})
        self.assertNotIn("_auth_user_id", self.client.session)


class PasswordChangeTests(AuthFixture):
    """Every auth page is mounted, so every one of them has to render.

    These are the pages nobody clicks during development, which is exactly how a
    missing template ships: the URL resolves, the view is happy, and the 500 only
    reaches a real user who follows the link in the header.
    """

    def test_change_password_page_renders_when_signed_in(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("password_change"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Change Password")

    def test_change_password_requires_being_signed_in(self):
        response = self.client.get(reverse("password_change"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_changing_the_password_takes_effect(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": "pw-1234-abcd",
                "new_password1": "new-one-9KX2qp",
                "new_password2": "new-one-9KX2qp",
            },
        )
        self.assertRedirects(response, reverse("password_change_done"))
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password("new-one-9KX2qp"))

    def test_wrong_current_password_does_not_change_it(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": "not-it",
                "new_password1": "new-one-9KX2qp",
                "new_password2": "new-one-9KX2qp",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.alice.check_password("pw-1234-abcd"))

    def test_done_page_renders(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("password_change_done"))
        self.assertEqual(response.status_code, 200)


class PasswordResetTests(AuthFixture):
    def test_request_page_renders(self):
        response = self.client.get(reverse("password_reset"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Send Reset Link")

    def test_done_page_renders(self):
        self.assertEqual(self.client.get(reverse("password_reset_done")).status_code, 200)

    def test_complete_page_renders(self):
        self.assertEqual(self.client.get(reverse("password_reset_complete")).status_code, 200)

    def test_requesting_a_reset_emails_a_working_link(self):
        response = self.client.post(
            reverse("password_reset"), {"email": self.alice.email}
        )
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)

    def test_unknown_address_sends_nothing_but_looks_the_same(self):
        response = self.client.post(reverse("password_reset"), {"email": "nobody@example.com"})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_the_link_in_the_email_sets_a_working_password(self):
        self.client.post(reverse("password_reset"), {"email": self.alice.email})
        body = mail.outbox[0].body
        path = re.search(r"(/accounts/reset/\S+)", body).group(1)

        # Django moves the token into the session and redirects, so that it can
        # never leak through an HTTP Referer header. The form is on the URL that
        # redirect lands on, not the one in the email.
        confirm = self.client.get(path, follow=True)
        self.assertEqual(confirm.status_code, 200)
        self.assertTrue(confirm.context["validlink"])
        form_url = confirm.request["PATH_INFO"]

        confirm = self.client.post(
            form_url, {"new_password1": "brand-new-7Qs3vd", "new_password2": "brand-new-7Qs3vd"}
        )
        self.assertRedirects(confirm, reverse("password_reset_complete"))

        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password("brand-new-7Qs3vd"))
        self.assertFalse(self.alice.check_password("pw-1234-abcd"))

    def test_a_reset_link_cannot_be_reused(self):
        self.client.post(reverse("password_reset"), {"email": self.alice.email})
        path = re.search(r"(/accounts/reset/\S+)", mail.outbox[0].body).group(1)
        form_url = self.client.get(path, follow=True).request["PATH_INFO"]
        self.client.post(
            form_url, {"new_password1": "brand-new-7Qs3vd", "new_password2": "brand-new-7Qs3vd"}
        )
        # Setting the password changes the hash the token was built from, so the
        # same emailed link is now worthless.
        replay = self.client.get(path, follow=True)
        self.assertEqual(replay.status_code, 200)
        self.assertFalse(replay.context["validlink"])

    def test_a_bogus_link_renders_the_expired_page_rather_than_a_500(self):
        response = self.client.get(reverse("password_reset_confirm", args=["MQ", "not-a-token"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid Reset Link")
