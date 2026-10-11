"""Who gets told what: submissions, reviews, role requests and trip access."""
from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import RoleRequest
from apps.activities.models import ActivityCategory
from apps.approval_system.models import ApprovalSettings, ApprovalStatus
from apps.events.models import Event
from apps.locations.models import City, Country
from apps.notifications.models import Notification
from apps.trips.models import Trip, TripGrant, TripRole

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class NotificationFlowTests(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada", "ada@example.com", "pw-1234-abcd")
        self.staffer = User.objects.create_user("staffer", "s@example.com", "pw-1234-abcd", is_staff=True)
        self.staffer.user_permissions.add(Permission.objects.get(codename="can_access_staff_dashboard",
                                                                 content_type__app_label="accounts"))
        country = Country.objects.create(name="Testland", slug="testland", iso_code="TL", iso3_code="TLD",
                                         continent="Europe", approval_status=ApprovalStatus.APPROVED)
        self.city = City.objects.create(name="Testville", slug="testville", country=country, latitude=1, longitude=2,
                                        approval_status=ApprovalStatus.APPROVED)
        self.music = ActivityCategory.objects.get(name="Music")

    def notes(self, user):
        return list(Notification.objects.filter(user=user).values_list("notification_type__name", "title"))

    def submit_event(self):
        self.client.force_login(self.ada)
        self.client.post(reverse("events:event_add"), {
            "name": "Jazz Night", "category": self.music.pk, "description": "Live jazz.", "city": self.city.pk,
            "start_date": "2027-05-01", "event_type": "public", "is_free": "on"})
        return Event.objects.get(name="Jazz Night")

    def test_submission_tells_staff_and_review_tells_the_submitter(self):
        event = self.submit_event()
        self.assertEqual(self.notes(self.staffer), [("submission_received", "New event to review: “Jazz Night (2027-05-01)”")])
        self.assertEqual(self.notes(self.ada), [])  # not told about their own submission
        mail.outbox.clear()
        event.approve(self.staffer, "Looks great")
        (kind, title), = self.notes(self.ada)
        self.assertEqual(kind, "submission_reviewed")
        self.assertIn("was approved", title)
        self.assertIn("Looks great", Notification.objects.get(user=self.ada).message)
        self.assertEqual(Notification.objects.get(user=self.ada).action_url, reverse("events:event_detail", args=[event.slug]))
        self.assertEqual([m.to for m in mail.outbox], [["ada@example.com"]])
        self.assertEqual(len(self.notes(self.staffer)), 1)  # the reviewer isn't told about their own review

    def test_rejection_and_changes_requested(self):
        event = self.submit_event()
        event.reject(self.staffer, "Duplicate")
        event.request_changes(self.staffer, "Add a venue")
        titles = [t for _, t in self.notes(self.ada)]
        self.assertTrue(any("wasn't approved" in t for t in titles) and any("needs changes" in t for t in titles))

    def test_switches_in_approval_settings(self):
        settings_ = ApprovalSettings.get_settings()
        settings_.notify_on_submission = settings_.notify_on_approval = False
        settings_.save()
        event = self.submit_event()
        event.approve(self.staffer)
        self.assertEqual(Notification.objects.count(), 0)

    def test_activity_submission_now_logs_and_tells_staff(self):
        from apps.activities.models import Activity
        self.client.force_login(self.ada)
        self.client.post(reverse("activities:activity_quick_add"), {
            "category": self.music.pk, "name": "Lake Swim", "description": "Cold.", "visibility": "public"})
        activity = Activity.objects.get(name="Lake Swim")
        self.assertEqual(activity.approval_status, ApprovalStatus.PENDING)
        self.assertEqual([k for k, _ in self.notes(self.staffer)], ["submission_received"])

    def test_role_request_decisions(self):
        request = RoleRequest.objects.create(user=self.ada, requested_role=RoleRequest.RequestedRole.VENDOR)
        request.reject(self.staffer, "Need a business licence")
        (kind, title), = self.notes(self.ada)
        self.assertEqual(kind, "role_request_decided")
        self.assertIn("Need a business licence", Notification.objects.get(user=self.ada).message)

    def test_trip_access(self):
        trip = Trip.objects.create(name="Rome", start_date=date(2027, 4, 1), end_date=date(2027, 4, 8))
        TripGrant.objects.create(trip=trip, user=self.ada, granted_by=self.staffer, role=TripRole.VIEWER)
        TripGrant.objects.create(trip=trip, user=self.staffer, granted_by=self.staffer, role=TripRole.EDITOR)  # self-grant
        self.assertEqual(self.notes(self.ada), [("trip_access_granted", "You were added to “Rome”")])
        self.assertIn("as viewer", Notification.objects.get(user=self.ada).message)
        self.assertEqual(self.notes(self.staffer), [])
