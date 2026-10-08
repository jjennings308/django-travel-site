from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event, EventCategory
from apps.locations.models import City, Country

User = get_user_model()
TODAY = date.today()


class EventFixture(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", "alice@example.com", "pw-1234-abcd")
        self.bob = User.objects.create_user("bob", "bob@example.com", "pw-1234-abcd")
        self.staff = User.objects.create_user("staff", "staff@example.com", "pw-1234-abcd", is_staff=True)
        country = Country.objects.create(name="Testland", slug="testland", iso_code="TL", iso3_code="TLD", continent="Europe")
        self.city = City.objects.create(name="Testville", slug="testville", country=country, latitude=1, longitude=2,
                                        approval_status=ApprovalStatus.APPROVED)
        self.music = EventCategory.objects.get(name="Music")  # seeded by migration 0003

    def make(self, name, status=ApprovalStatus.APPROVED, start=None, **kw):
        return Event.objects.create(name=name, category=self.music, description="d", city=self.city,
                                    start_date=start or TODAY + timedelta(days=10),
                                    approval_status=status, **kw)

    def payload(self, **over):
        data = {"name": "Jazz Night", "category": self.music.pk, "description": "Live jazz.",
                "city": self.city.pk, "start_date": (TODAY + timedelta(days=5)).isoformat(),
                "event_type": "public", "is_free": "on"}
        data.update(over)
        return data


class ListAndVisibilityTests(EventFixture):
    def test_list_shows_only_approved_upcoming(self):
        self.make("Approved Gig")
        self.make("Pending Gig", status=ApprovalStatus.PENDING)
        self.make("Old Gig", start=TODAY - timedelta(days=30))
        response = self.client.get(reverse("events:event_list"))
        self.assertContains(response, "Approved Gig")
        self.assertNotContains(response, "Pending Gig")
        self.assertNotContains(response, "Old Gig")
        self.assertContains(self.client.get(reverse("events:event_list") + "?when=past"), "Old Gig")

    def test_filters(self):
        self.make("Free Gig", is_free=True)
        self.make("Paid Gig", is_free=False)
        response = self.client.get(reverse("events:event_list") + "?free=1&q=gig")
        self.assertContains(response, "Free Gig")
        self.assertNotContains(response, "Paid Gig")

    def test_unapproved_event_is_404_except_for_creator_and_staff(self):
        event = self.make("Secret", status=ApprovalStatus.PENDING, created_by=self.alice)
        url = reverse("events:event_detail", args=[event.slug])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(url), "Only you and our team can see this event")
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 200)


class SubmitAndEditTests(EventFixture):
    def test_user_submission_goes_to_review(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse("events:event_add"), self.payload())
        event = Event.objects.get(name="Jazz Night")
        self.assertRedirects(response, reverse("events:event_detail", args=[event.slug]))
        self.assertEqual((event.approval_status, event.created_by, event.submitted_by), (ApprovalStatus.PENDING, self.alice, self.alice))
        self.assertContains(self.client.get(reverse("events:my_events")), "Jazz Night")
        self.assertNotContains(self.client.get(reverse("events:event_list")), "Jazz Night")

    def test_staff_submission_is_published(self):
        self.client.force_login(self.staff)
        self.client.post(reverse("events:event_add"), self.payload())
        self.assertEqual(Event.objects.get(name="Jazz Night").approval_status, ApprovalStatus.APPROVED)

    def test_approval_publishes_it(self):
        event = self.make("Queued", status=ApprovalStatus.PENDING, created_by=self.alice)
        event.approve(self.staff)
        self.assertContains(self.client.get(reverse("events:event_list")), "Queued")

    def test_creator_can_edit_until_approved(self):
        event = self.make("Mine", status=ApprovalStatus.PENDING, created_by=self.alice)
        self.client.force_login(self.alice)
        edit = reverse("events:event_edit", args=[event.slug])
        self.assertEqual(self.client.get(edit).status_code, 200)
        Event.objects.filter(pk=event.pk).update(approval_status=ApprovalStatus.APPROVED)
        self.assertRedirects(self.client.get(edit), reverse("events:event_detail", args=[event.slug]))

    def test_editing_a_rejected_event_resubmits_it(self):
        event = self.make("Fix me", status=ApprovalStatus.REJECTED, created_by=self.alice)
        self.client.force_login(self.alice)
        self.client.post(reverse("events:event_edit", args=[event.slug]), self.payload(name="Fixed"))
        event.refresh_from_db()
        self.assertEqual((event.name, event.approval_status), ("Fixed", ApprovalStatus.PENDING))

    def test_others_cannot_edit_or_delete(self):
        event = self.make("Alice's", created_by=self.alice)
        self.client.force_login(self.bob)
        self.client.post(reverse("events:event_delete", args=[event.slug]))
        self.assertTrue(Event.objects.filter(pk=event.pk).exists())

    def test_creator_can_delete_pending(self):
        event = self.make("Oops", status=ApprovalStatus.PENDING, created_by=self.alice)
        self.client.force_login(self.alice)
        self.assertRedirects(self.client.post(reverse("events:event_delete", args=[event.slug])), reverse("events:my_events"))
        self.assertFalse(Event.objects.filter(pk=event.pk).exists())

    def test_end_before_start_is_rejected(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse("events:event_add"), self.payload(
            end_date=(TODAY + timedelta(days=1)).isoformat()))
        self.assertContains(response, "can&#x27;t be before the start date")
        self.assertFalse(Event.objects.exists())

    def test_add_requires_login(self):
        self.assertEqual(self.client.get(reverse("events:event_add")).status_code, 302)
