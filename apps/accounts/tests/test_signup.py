"""Invite-only sign-up and sign-up codes (site roadmap R14)."""
import time
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import RoleRequest, SignupCode
from apps.accounts.views import SIGNUP_SESSION_KEY

User = get_user_model()


def form(username="newbie", **extra):
    return {"username": username, "email": f"{username}@example.com", "first_name": "New", "last_name": "Person",
            "password1": "a-Long-pass-9876", "password2": "a-Long-pass-9876", "terms_accepted": "on", **extra}


@override_settings(SIGNUP_MODE="invite")
class InviteOnlyTests(TestCase):
    url = reverse("register")

    def test_without_an_invite_or_code_it_explains(self):
        page = self.client.get(self.url)
        self.assertTemplateUsed(page, "accounts/register_closed.html")
        self.assertContains(page, "Sign-up is by invitation")
        self.client.post(self.url, form())
        self.assertFalse(User.objects.filter(username="newbie").exists())

    def test_a_code_lets_them_in_and_is_used_up(self):
        code = SignupCode.objects.create(code="abcd2345", uses_left=1)
        page = self.client.get(self.url, {"code": "ABCD 2345"})
        self.assertTemplateUsed(page, "accounts/register.html")
        self.assertContains(page, 'name="signup_code" value="ABCD2345"')
        self.client.post(self.url, form(signup_code="ABCD2345"))
        self.assertTrue(User.objects.filter(username="newbie").exists())
        code.refresh_from_db()
        self.assertEqual(code.uses_left, 0)
        self.client.post(self.url, form("second", signup_code="ABCD2345"))
        self.assertFalse(User.objects.filter(username="second").exists())

    def test_expired_or_unknown_codes_are_refused(self):
        SignupCode.objects.create(code="OLDCODE2", expires_at=timezone.now() - timedelta(days=1))
        for code in ("OLDCODE2", "NOSUCH22"):
            page = self.client.get(self.url, {"code": code})
            self.assertContains(page, "isn't valid")

    def test_a_trip_invite_lets_them_in(self):
        session = self.client.session
        session[SIGNUP_SESSION_KEY] = time.time() + 600
        session.save()
        self.client.post(self.url, form())
        self.assertTrue(User.objects.filter(username="newbie").exists())

    def test_staff_can_always_create_accounts(self):
        staff = User.objects.create_superuser("root", "root@example.com", "pw-1234-abcd")
        self.client.force_login(staff)
        self.assertTemplateUsed(self.client.get(self.url), "accounts/register.html")


@override_settings(SIGNUP_MODE="open")
class OpenSignupTests(TestCase):
    def test_anyone(self):
        response = self.client.post(reverse("register"), form())
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="newbie").exists())

    def test_no_role_boxes_and_settings_links_the_request_page(self):
        page = self.client.get(reverse("register"))
        self.assertNotContains(page, "request_vendor_role")
        self.client.post(reverse("register"), form(request_vendor_role="on"))
        self.assertFalse(RoleRequest.objects.exists())
        user = User.objects.get(username="newbie")
        user.is_active = True
        user.save()
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("settings")), reverse("request_role"))
