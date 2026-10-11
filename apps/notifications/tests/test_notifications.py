"""The notify service and the user's notification pages."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.notifications.models import Notification
from apps.notifications.services import notify, notify_staff, staff_recipients

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", SITE_URL="https://example.com")
class ServiceTests(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada", "ada@example.com", "pw-1234-abcd")

    def test_creates_a_row_and_emails_with_a_full_link(self):
        note = notify(self.ada, "submission_reviewed", "Approved", "Your event is live.", "/events/x/")
        self.assertEqual((note.user, note.notification_type.name, note.channels, note.email_sent),
                         (self.ada, "submission_reviewed", ["in_app", "email"], True))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("https://example.com/events/x/", mail.outbox[0].body)

    def test_no_email_when_turned_off_or_placeholder_address(self):
        from apps.accounts.models import AccountSettings
        settings_, _ = AccountSettings.objects.get_or_create(user=self.ada)
        settings_.email_notifications = False
        settings_.save()
        ghost = User.objects.create_user("ghost", "ghost@noemail.invalid", "pw-1234-abcd")
        notify(User.objects.get(pk=self.ada.pk), "submission_reviewed", "t", "m")
        notify(ghost, "submission_reviewed", "t", "m")
        self.assertEqual((Notification.objects.count(), len(mail.outbox)), (2, 0))

    def test_mail_failure_does_not_raise(self):
        with mock.patch("apps.notifications.services.EmailMessage.send", side_effect=OSError("smtp down")):
            note = notify(self.ada, "trip_access_granted", "t", "m")
        self.assertFalse(note.email_sent)

    def test_staff_recipients(self):
        perm = Permission.objects.get(codename="can_access_staff_dashboard", content_type__app_label="accounts")
        staffer = User.objects.create_user("staffer", "s@example.com", "pw-1234-abcd")
        staffer.user_permissions.add(perm)
        boss = User.objects.create_superuser("boss", "b@example.com", "pw-1234-abcd")
        self.assertEqual(set(staff_recipients()), {staffer, boss})
        notify_staff("submission_received", "New", "m", exclude=boss)
        self.assertEqual(list(Notification.objects.values_list("user__username", flat=True)), ["staffer"])


class PageTests(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada", "ada@example.com", "pw-1234-abcd")
        self.bob = User.objects.create_user("bob", "bob@example.com", "pw-1234-abcd")
        self.note = notify(self.ada, "trip_access_granted", "You were added to “Rome”", "m", "/trips/")
        notify(self.ada, "submission_reviewed", "Approved", "m", "")
        self.client.force_login(self.ada)

    def test_bell_feed(self):
        data = self.client.get(reverse("notifications:unread_count")).json()
        self.assertEqual(data["unread"], 2)
        self.assertEqual(data["latest"][1]["title"], "You were added to “Rome”")

    def test_open_marks_read_and_redirects(self):
        response = self.client.get(reverse("notifications:open", args=[self.note.pk]))
        self.assertRedirects(response, "/trips/", fetch_redirect_response=False)
        self.note.refresh_from_db()
        self.assertTrue(self.note.is_read)

    def test_others_cannot_open_and_mark_all(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(reverse("notifications:open", args=[self.note.pk])).status_code, 404)
        self.client.force_login(self.ada)
        self.client.post(reverse("notifications:mark_all_read"))
        self.assertEqual(self.client.get(reverse("notifications:unread_count")).json()["unread"], 0)
        self.assertContains(self.client.get(reverse("notifications:list")), "all caught up")

    def test_bell_in_header(self):
        self.assertContains(self.client.get(reverse("notifications:list")), reverse("notifications:unread_count"))
