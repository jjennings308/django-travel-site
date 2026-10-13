"""Home page claims match the site; footer links go somewhere; Contact and Help pages."""
import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import Resolver404, resolve, reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import Country

LEGAL = {"entity": "Co", "contact_email": "hello@example.com", "postal_address": "1 St", "jurisdiction": "PA",
         "effective_date": "2026-01-01", "min_age": "16"}


@override_settings(LEGAL=LEGAL, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SitePagesTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_home_shows_real_counts_and_no_invented_claims(self):
        Country.objects.create(name="Testland", slug="testland", iso_code="TL", iso3_code="TLD", continent="Europe",
                               approval_status=ApprovalStatus.APPROVED)
        page = self.client.get(reverse("pages:home"))
        self.assertEqual(page.context["catalogue"]["countries"], 1)
        for invented in ("10K+", "50K+", "100K+", "Sarah Johnson", "pravatar", "Cancel anytime", "earn badges"):
            self.assertNotContains(page, invented)

    def test_footer_links_all_go_somewhere(self):
        html = self.client.get(reverse("pages:about")).content.decode()
        footer = html[html.index("<footer"):]
        links = re.findall(r'href="([^"]+)"', footer)
        self.assertTrue(links)
        for href in links:
            with self.subTest(href=href):
                self.assertNotEqual(href, "#")
                try:
                    resolve(href.split("#")[0])
                except Resolver404:
                    self.fail(f"footer link {href} doesn't resolve")

    def test_features_page(self):
        page = self.client.get(reverse("pages:features"))
        for step in ("Discover", "Dream", "Pick a date", "Plan", "Done"):
            self.assertContains(page, step)
        self.assertContains(page, reverse("register"))
        self.assertContains(self.client.get(reverse("pages:home")), reverse("pages:features"))
        user = get_user_model().objects.create_user(username="f", email="f@example.com", password="pw")
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("pages:features")), reverse("pages:dashboard"))

    def test_about_page_tells_what_the_site_is(self):
        page = self.client.get(reverse("pages:about"))
        self.assertContains(page, "Why it exists")
        self.assertIn("catalogue", page.context)
        self.assertNotContains(page, "About this site.")

    def test_help_page(self):
        self.assertContains(self.client.get(reverse("pages:help")), "The five steps")

    def test_contact_sends_with_reply_to(self):
        data = {"name": "Ada", "email": "ada@example.com", "subject": "Hi", "message": "Love it", "website": ""}
        response = self.client.post(reverse("pages:contact"), data, follow=True)
        self.assertContains(response, "your message was sent")
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual((msg.to, msg.reply_to), (["hello@example.com"], ["ada@example.com"]))
        self.assertIn("Love it", msg.body)

    def test_honeypot_and_limit(self):
        data = {"name": "Bot", "email": "b@example.com", "subject": "x", "message": "spam", "website": "http://spam"}
        self.client.post(reverse("pages:contact"), data)
        self.assertEqual(len(mail.outbox), 0)
        data["website"] = ""
        for _ in range(4):
            response = self.client.post(reverse("pages:contact"), data, follow=True)
        self.assertEqual(len(mail.outbox), 3)
        self.assertContains(response, "try again in an hour")

    @override_settings(LEGAL={**LEGAL, "contact_email": "[privacy@your-domain]"})
    def test_disabled_until_the_address_is_set(self):
        page = self.client.get(reverse("pages:contact"))
        self.assertContains(page, "hasn't been set up yet")
        self.client.post(reverse("pages:contact"), {"name": "A", "email": "a@example.com", "subject": "s", "message": "m"})
        self.assertEqual(len(mail.outbox), 0)

    def test_signed_in_user_is_prefilled(self):
        user = get_user_model().objects.create_user("ada", "ada@example.com", "pw-1234-abcd")
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("pages:contact")), 'value="ada@example.com"')


class DashboardRecommendationTests(TestCase):
    def test_dashboard_shows_real_suggestions_not_the_old_placeholders(self):
        from apps.activities.models import Activity, ActivityCategory
        user = get_user_model().objects.create_user("u", "u@example.com", "pw-1234-abcd")
        Activity.objects.create(category=ActivityCategory.objects.get(name="Festival"), name="Lantern festival",
                                description="Lights.", created_by=user, visibility="public",
                                approval_status=ApprovalStatus.APPROVED)
        self.client.force_login(user)
        page = self.client.get(reverse("pages:dashboard"))
        self.assertContains(page, "Lantern festival")
        self.assertNotContains(page, "Explore Paris")
        self.assertNotContains(page, "unsplash")
