"""Per-visitor rate limits (site roadmap R15)."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

User = get_user_model()


@override_settings(RATELIMIT_ENABLED=True, SIGNUP_MODE="open")
class RateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_user("ada", "ada@example.com", "pw-1234-abcd")

    def test_login_attempts(self):
        url = reverse("login")
        for _ in range(10):
            self.assertNotEqual(self.client.post(url, {"username": "ada@example.com", "password": "wrong"}).status_code, 429)
        blocked = self.client.post(url, {"username": "ada@example.com", "password": "pw-1234-abcd"})
        self.assertEqual(blocked.status_code, 429)
        self.assertContains(blocked, "Too many attempts", status_code=429)
        self.assertNotContains(blocked, "ada", status_code=429)  # says nothing about the account
        self.assertTrue(blocked.has_header("Retry-After"))
        # Another visitor (nginx's X-Real-IP) isn't affected; a GET of the page always works.
        other = self.client.post(url, {"username": "x", "password": "y"}, HTTP_X_REAL_IP="203.0.113.9")
        self.assertNotEqual(other.status_code, 429)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_password_reset_requests(self):
        url = reverse("password_reset")
        for _ in range(5):
            self.client.post(url, {"email": "nobody@example.com"})
        self.assertEqual(self.client.post(url, {"email": "ada@example.com"}).status_code, 429)

    @override_settings(SIGNUP_MODE="invite")
    def test_guessing_signup_codes(self):
        url = reverse("register")
        for n in range(10):
            self.assertEqual(self.client.get(url, {"code": f"WRONG{n:03d}"}).status_code, 200)
        self.assertEqual(self.client.get(url, {"code": "WRONG999"}).status_code, 429)

    def test_off_in_test_settings_by_default(self):
        with override_settings(RATELIMIT_ENABLED=False):
            for _ in range(15):
                self.assertNotEqual(self.client.post(reverse("login"), {"username": "a", "password": "b"}).status_code, 429)
