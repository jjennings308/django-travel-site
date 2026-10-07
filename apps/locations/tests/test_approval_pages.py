"""Approval system pages, exercised with a City: every Approvable model is in layer 3, so these
tests live here rather than in approval_system (layer 2), which may not import locations."""

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalLog, ApprovalQueue, ApprovalStatus
from apps.locations.models import City, Country

User = get_user_model()


class ApprovalPageTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", "staff@example.com", "pw-1234-abcd", is_staff=True)
        self.alice = User.objects.create_user("alice", "alice@example.com", "pw-1234-abcd")
        country = Country.objects.create(name="Testland", slug="testland", iso_code="TL", iso3_code="TLD", continent="Europe")
        self.city = City.objects.create(
            name="Testville", slug="testville", country=country, latitude=1, longitude=2,
            approval_status=ApprovalStatus.PENDING, submitted_by=self.alice,
        )
        self.queue = ApprovalQueue.objects.create(name="Locations", slug="locations", status_filter=ApprovalStatus.PENDING, icon="📍")
        self.queue.content_types.add(ContentType.objects.get_for_model(City))
        self.review_url = reverse("approval_system:review_item", args=[ContentType.objects.get_for_model(City).id, self.city.id])

    def test_staff_pages_render(self):
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("approval_system:dashboard")), "Locations")
        self.assertContains(self.client.get(reverse("approval_system:queue_detail", args=["locations"])), "Testville")
        self.assertContains(self.client.get(self.review_url), "Testville")
        self.assertContains(self.client.get(reverse("approval_system:stats") + "?days=7"), "last 7 days")

    def test_my_submissions_lists_the_users_items(self):
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(reverse("approval_system:my_submissions")), "Testville")

    def test_approving_from_the_review_page(self):
        self.client.force_login(self.staff)
        queue_url = reverse("approval_system:queue_detail", args=["locations"])
        response = self.client.post(self.review_url, {"action": "approve", "notes": "Looks right", "priority": "normal", "next": queue_url})
        self.assertRedirects(response, queue_url)
        self.city.refresh_from_db()
        self.assertEqual(self.city.approval_status, ApprovalStatus.APPROVED)
        self.assertTrue(ApprovalLog.objects.filter(action="approved").exists())
        self.assertContains(self.client.get(reverse("approval_system:stats")), "Approved")

    def test_non_staff_cannot_review(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(self.review_url).status_code, 302)
