"""Storage limit, unsubscribe, reports and suspension (site roadmap R15)."""
import shutil
import tempfile
from datetime import date

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.activities.models import Activity, ActivityCategory
from apps.admin_tools.models import ReportedContent
from apps.approval_system.models import ApprovalStatus
from apps.bucketlists.models import BucketListItem
from apps.locations.models import POI
from apps.media_app import quota
from apps.media_app.models import Media
from apps.notifications.models import Notification, UserNotificationPreference
from apps.notifications.services import notify, unsubscribe_token
from apps.trips import files
from apps.trips.models import Confirmation, Lodging, Trip, TripGrant

User = get_user_model()


def png():
    from io import BytesIO
    from PIL import Image
    out = BytesIO()
    Image.new("RGB", (10, 10), "red").save(out, format="PNG")
    return out.getvalue()


class FilesFixture(TestCase):
    def setUp(self):
        roots = tempfile.mkdtemp(), tempfile.mkdtemp()
        for folder in roots:
            self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=roots[0], PRIVATE_MEDIA_ROOT=roots[1],
                                     EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
        override.enable()
        self.addCleanup(override.disable)
        self.ada = User.objects.create_user("ada", "ada@example.com", "pw-1234-abcd")


@override_settings(STORAGE_LIMIT_MB=1)
class QuotaTests(FilesFixture):
    def fill(self, nbytes):
        Media.objects.create(file=ContentFile(b"x" * nbytes, name="big.jpg"), uploaded_by=self.ada, media_type="image")

    def test_photos_count_and_uploads_are_refused_with_a_message(self):
        self.fill(1024 * 1024 - 10)  # less room than even a tiny PNG
        goal = BucketListItem.objects.create(user=self.ada, custom_title="Alps")
        self.client.force_login(self.ada)
        url = reverse("bucketlists:item_photos", args=[goal.pk])
        response = self.client.post(url, {"photos": [SimpleUploadedFile("a.png", png(), "image/png")]}, follow=True)
        self.assertContains(response, "Not uploaded: you&#x27;ve used")
        self.assertContains(response, "of your 1 MB")
        self.assertEqual(Media.objects.filter(uploaded_by=self.ada).count(), 1)

    def test_tickets_count_towards_it_and_are_refused(self):
        trip = Trip.objects.create(name="Rome", start_date=date(2027, 5, 1), end_date=date(2027, 5, 2), created_by=self.ada)
        TripGrant.objects.create(trip=trip, user=self.ada, role="editor")
        stay = Lodging.objects.create(trip=trip, name="Inn", check_in=date(2027, 5, 1), check_out=date(2027, 5, 2))
        confirmation = Confirmation.attach_number(trip, "R1", stay)
        files.add(confirmation, SimpleUploadedFile("a.pdf", b"%PDF-" + b"x" * 600_000), self.ada)
        self.assertGreater(quota.used(self.ada), 600_000)
        with self.assertRaises(files.Refused):
            files.add(confirmation, SimpleUploadedFile("b.pdf", b"%PDF-" + b"x" * 600_000), self.ada)

    def test_staff_unlimited(self):
        staff = User.objects.create_superuser("root", "root@example.com", "pw-1234-abcd")
        quota.check(staff, 10 ** 12)  # no error


class UnsubscribeTests(FilesFixture):
    def test_email_has_a_working_one_click_link_for_that_kind_only(self):
        notify(self.ada, "trip_changed", "Changes", "Something changed", "/trips/")
        message = mail.outbox[-1]
        link = message.extra_headers["List-Unsubscribe"].strip("<>")
        self.assertEqual(message.extra_headers["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        self.assertIn(link, message.body)
        path = link.split("://", 1)[1].split("/", 1)[1]
        page = self.client.get("/" + path)  # signed out
        self.assertContains(page, "Stop these emails")
        response = self.client.post("/" + path, {"List-Unsubscribe": "One-Click"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(UserNotificationPreference.objects.filter(user=self.ada, email_enabled=False,
                                                                  notification_type__name="trip_changed").exists())
        mail.outbox = []
        notify(self.ada, "trip_changed", "More", "m")
        self.assertEqual(mail.outbox, [])  # that kind is off
        self.assertTrue(Notification.objects.filter(title="More").exists())  # still under the bell
        notify(self.ada, "trip_access_granted", "Added", "m")
        self.assertEqual(len(mail.outbox), 1)  # other kinds still email

    def test_undo_and_tampered_tokens(self):
        token = unsubscribe_token(self.ada, "trip_changed")
        url = reverse("notifications:unsubscribe", args=[token])
        self.client.post(url)
        self.client.post(url, {"undo": "1"})
        self.assertTrue(UserNotificationPreference.objects.get(user=self.ada).email_enabled)
        self.assertEqual(self.client.get(reverse("notifications:unsubscribe", args=[token[:-2] + "xx"])).status_code, 404)


class ReportTests(FilesFixture):
    def setUp(self):
        super().setUp()
        category, _ = ActivityCategory.objects.get_or_create(name="Tours", defaults={"slug": "tours"})
        self.member = User.objects.create_user("mem", "mem@example.com", "pw-1234-abcd")
        self.activity = Activity.objects.create(name="Fake tour", category=category, created_by=self.member,
                                                submitted_by=self.member, description="x", visibility="public",
                                                approval_status=ApprovalStatus.APPROVED)
        self.staff = User.objects.create_superuser("root", "root@example.com", "pw-1234-abcd")

    def report(self, user, kind="activity", obj=None):
        obj = obj or self.activity
        self.client.force_login(user)
        return self.client.post(reverse("reports:report", args=[kind, obj.pk]), {"reason": "spam"})

    def test_three_reports_hide_a_member_activity(self):
        reporters = [User.objects.create_user(f"r{n}", f"r{n}@example.com", "pw-1234-abcd") for n in range(3)]
        self.report(reporters[0])
        self.report(reporters[0])  # twice from one person counts once
        self.assertEqual(ReportedContent.objects.count(), 1)
        self.report(reporters[1])
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.approval_status, ApprovalStatus.APPROVED)
        self.report(reporters[2])
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.approval_status, ApprovalStatus.PENDING)
        self.assertTrue(Notification.objects.filter(user=self.staff, notification_type__name="content_reported").exists())

    def test_places_only_notify(self):
        from apps.locations.models import City, Country
        country = Country.objects.create(name="Testland", slug="testland", iso_code="TL", iso3_code="TST",
                                         continent="EU")
        city = City.objects.create(name="Testville", slug="testville", country=country, latitude=1, longitude=1)
        poi = POI.objects.create(name="Old bridge", slug="old-bridge", city=city, latitude=1, longitude=1)
        for n in range(3):
            self.report(User.objects.create_user(f"p{n}", f"p{n}@example.com", "pw-1234-abcd"), "place", poi)
        response = self.report(self.ada, "place", poi)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ReportedContent.objects.filter(object_id=poi.pk).count(), 4)
        self.assertTrue(POI.objects.filter(pk=poi.pk).exists())  # never hidden automatically

    def test_report_link_on_the_page_and_signed_in_only(self):
        self.client.force_login(self.ada)
        page = self.client.get(reverse("activities:activity_detail", args=[self.activity.slug]))
        self.assertContains(page, reverse("reports:report", args=["activity", self.activity.pk]))
        self.client.logout()
        self.assertEqual(self.client.get(reverse("reports:report", args=["activity", self.activity.pk])).status_code, 302)


class SuspendTests(FilesFixture):
    def test_suspending_blocks_sign_in_and_trip_access(self):
        staff = User.objects.create_superuser("root", "root@example.com", "pw-1234-abcd")
        trip = Trip.objects.create(name="Rome", start_date=date(2027, 5, 1), end_date=date(2027, 5, 2))
        TripGrant.objects.create(trip=trip, user=self.ada, role="viewer")
        self.client.force_login(staff)
        self.client.post(reverse("admin:accounts_user_changelist"),
                         {"action": "suspend_accounts", "_selected_action": [self.ada.pk]})
        self.ada.refresh_from_db()
        self.assertFalse(self.ada.is_active)
        self.assertIsNotNone(self.ada.suspended_at)
        self.client.logout()
        response = self.client.post(reverse("login"), {"username": "ada@example.com", "password": "pw-1234-abcd"})
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(trip.can(self.ada, "view"))
        self.client.force_login(staff)
        self.client.post(reverse("admin:accounts_user_changelist"),
                         {"action": "unsuspend_accounts", "_selected_action": [self.ada.pk]})
        self.ada.refresh_from_db()
        self.assertTrue(self.ada.is_active)
