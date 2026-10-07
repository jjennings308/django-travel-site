from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import RoleRequest

User = get_user_model()


class RoleRequestFlowTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", "alice@example.com", "pw-1234-abcd")
        self.staff = User.objects.create_superuser("boss", "boss@example.com", "pw-1234-abcd")

    def submit(self):
        self.client.force_login(self.alice)
        return self.client.post(reverse("request_role"), {
            "requested_role": RoleRequest.RequestedRole.VENDOR,
            "business_name": "Alice Tours",
            "business_description": "Small-group walking tours.",
        })

    def test_request_page_renders(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("request_role"))
        self.assertContains(response, "Request a Role")
        self.assertContains(response, 'enctype="multipart/form-data"')

    def test_submitting_creates_a_pending_request(self):
        self.assertRedirects(self.submit(), reverse("profile"))
        rr = RoleRequest.objects.get(user=self.alice)
        self.assertEqual(rr.status, RoleRequest.Status.PENDING)
        response = self.client.get(reverse("role_request_status"))
        self.assertContains(response, "Alice Tours")
        self.assertContains(response, "Pending Review")

    def test_staff_list_shows_pending_requests(self):
        self.submit()
        self.client.force_login(self.staff)
        response = self.client.get(reverse("staff:admin_role_requests"))
        self.assertContains(response, "@alice")

    def test_approving_grants_the_role_and_returns_to_the_list(self):
        self.submit()
        rr = RoleRequest.objects.get(user=self.alice)
        self.client.force_login(self.staff)
        url = reverse("staff:admin_role_request_detail", args=[rr.id])
        self.assertContains(self.client.get(url), "Alice Tours")
        response = self.client.post(url, {"action": "approve", "review_notes": "ok"})
        self.assertRedirects(response, reverse("staff:admin_role_requests"))
        rr.refresh_from_db()
        self.assertEqual(rr.status, RoleRequest.Status.APPROVED)
        self.assertTrue(self.alice.groups.filter(name="Vendors").exists())

    def test_rejecting_needs_a_reason(self):
        self.submit()
        rr = RoleRequest.objects.get(user=self.alice)
        self.client.force_login(self.staff)
        url = reverse("staff:admin_role_request_detail", args=[rr.id])
        response = self.client.post(url, {"action": "reject"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "rejection reason")
        response = self.client.post(url, {"action": "reject", "rejection_reason": "Need a licence"})
        self.assertRedirects(response, reverse("staff:admin_role_requests"))
        rr.refresh_from_db()
        self.assertEqual(rr.status, RoleRequest.Status.REJECTED)
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(reverse("role_request_status")), "Need a licence")

    def test_staff_pages_refuse_ordinary_users(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse("staff:admin_role_requests")).status_code, 302)


class AdminToggleStatusTests(TestCase):
    def test_toggle_redirects_back_to_the_account(self):
        staff = User.objects.create_superuser("boss", "boss@example.com", "pw-1234-abcd")
        alice = User.objects.create_user("alice", "alice@example.com", "pw-1234-abcd")
        self.client.force_login(staff)
        response = self.client.post(
            reverse("staff:admin_toggle_user_status", args=[alice.id]), {"action": "verify"}
        )
        self.assertRedirects(response, reverse("staff:admin_account_detail", args=[alice.id]))
        alice.refresh_from_db()
        self.assertTrue(alice.is_verified)
