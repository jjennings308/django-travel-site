from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class PageViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="traveler", email="traveler@example.com", password="pw-for-tests-only"
        )

    def test_home_renders_for_anonymous(self):
        response = self.client.get(reverse("pages:home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/home.html")

    def test_home_redirects_authenticated_to_dashboard(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("pages:home"))
        self.assertRedirects(response, reverse("pages:dashboard"))

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("pages:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_dashboard_renders(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("pages:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/dashboard.html")

    def test_about_renders(self):
        response = self.client.get(reverse("pages:about"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/about.html")
