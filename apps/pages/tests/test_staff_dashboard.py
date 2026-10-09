"""Staff dashboard: access, stats, and the 'needs attention' list."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import RoleRequest
from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event
from apps.locations.models import City, Country, Region

User = get_user_model()
URL = reverse("pages:staff_dashboard")
LEGAL_DONE = {"entity": "Co", "contact_email": "a@b.c", "postal_address": "1 St", "jurisdiction": "PA",
              "effective_date": "2026-01-01", "min_age": "16"}


@override_settings(LEGAL=LEGAL_DONE)
class StaffDashboardTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staffer", "s@example.com", "pw-1234-abcd")
        self.staff.user_permissions.add(Permission.objects.get(
            codename="can_access_staff_dashboard", content_type__app_label="accounts"))
        self.member = User.objects.create_user("member", "m@example.com", "pw-1234-abcd")
        self.country = Country.objects.create(name="Testland", slug="testland", iso_code="TL", iso3_code="TLD",
                                              continent="Europe", approval_status=ApprovalStatus.APPROVED)
        self.client.force_login(self.staff)

    def test_access(self):
        self.client.logout()
        self.assertRedirects(self.client.get(URL), f"{reverse('login')}?next={URL}", fetch_redirect_response=False)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_linked_for_staff_only(self):
        self.assertContains(self.client.get(reverse("pages:dashboard")), URL)  # Quick Access card
        self.client.force_login(self.member)
        self.assertNotContains(self.client.get(reverse("pages:dashboard")), URL)
        self.member.is_staff = True
        self.member.save()
        self.assertContains(self.client.get(reverse("bucketlists:dashboard")), URL)  # header menu

    def test_nothing_to_do(self):
        self.assertContains(self.client.get(URL), "Nothing needs attention right now.")

    def test_lists_what_needs_attention(self):
        cat = ActivityCategory.objects.get(name="Festival")
        old = timezone.now() - timedelta(days=5)
        Activity.objects.create(category=cat, name="Pending Fest", description="d", created_by=self.member,
                                approval_status=ApprovalStatus.PENDING, submitted_at=old)
        Event.objects.create(name="Typed Town Gig", category=cat, description="d", country=self.country,
                             location_text="Smallville", start_date=timezone.now().date(),
                             approval_status=ApprovalStatus.APPROVED)
        Region.objects.create(country=self.country, name="North", slug="north")
        City.objects.create(name="Regionless", slug="regionless", country=self.country, latitude=1, longitude=2,
                            approval_status=ApprovalStatus.APPROVED)
        elsewhere = Country.objects.create(name="Otherland", slug="otherland", iso_code="OL", iso3_code="OTL", continent="Europe")
        City.objects.create(name="Mixed Up", slug="mixed-up", country=elsewhere, latitude=1, longitude=2,
                            region=Region.objects.get(name="North"), approval_status=ApprovalStatus.APPROVED)
        Activity.objects.create(category=cat, name="Okto", description="d", created_by=self.member, recurrence="yearly",
                                visibility="public", approval_status=ApprovalStatus.APPROVED)
        RoleRequest.objects.create(user=self.member, requested_role=RoleRequest.RequestedRole.VENDOR)
        User.objects.create_user("ghost", "ghost@noemail.invalid", "pw-1234-abcd")

        page = self.client.get(URL)
        for text in ("Submissions waiting for review", "Pending Fest", "past the",
                     "Events with a city that isn&#x27;t in the catalogue", "Typed Town Gig",
                     "Cities without a region", "Regionless", "Cities whose region is in a different country", "Mixed Up",
                     "Yearly activities with no upcoming dates", "Okto",
                     "Role requests", "@member", "Accounts with a placeholder email", "ghost"):
            self.assertContains(page, text)
        self.assertNotContains(page, "Nothing needs attention")

    @override_settings(LEGAL={**LEGAL_DONE, "entity": "[Legal entity name]"})
    def test_legal_placeholders(self):
        self.assertContains(self.client.get(URL), "LEGAL_ENTITY")

    def test_stats(self):
        page = self.client.get(URL)
        self.assertContains(page, "Members")
        self.assertContains(page, "Published catalogue")
        self.assertEqual(page.context["stats"]["users"]["total"], 2)
