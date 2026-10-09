"""Activities and events share one look: the banner header + Quick Info / Actions
on detail pages, and the same card on list pages."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event
from apps.locations.models import City, Country


class CatalogueStyleTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("u", "u@example.com", "pw-1234-abcd")
        country = Country.objects.create(name="Germany", slug="germany", iso_code="DE", iso3_code="DEU",
                                         continent="Europe", approval_status=ApprovalStatus.APPROVED)
        city = City.objects.create(name="Munich", slug="munich", country=country, latitude=48, longitude=11,
                                   approval_status=ApprovalStatus.APPROVED)
        festival = ActivityCategory.objects.get(name="Festival")
        self.activity = Activity.objects.create(category=festival, name="Oktoberfest", description="Beer", city=city,
                                                recurrence="yearly", usual_months=[9], created_by=user,
                                                visibility="public", approval_status=ApprovalStatus.APPROVED)
        self.event = Event.objects.create(name="Oktoberfest 2027", category=festival, description="Beer", city=city,
                                          related_activity=self.activity, start_date=date.today() + timedelta(days=30),
                                          approval_status=ApprovalStatus.APPROVED, status="cancelled")
        self.client.force_login(user)

    def test_detail_pages_share_the_layout(self):
        for url in (reverse("activities:activity_detail", args=[self.activity.slug]),
                    reverse("events:event_detail", args=[self.event.slug])):
            with self.subTest(url=url):
                page = self.client.get(url)
                for text in ("Quick Info", "Actions", "Munich, Germany", "Festival", "text-4xl font-bold md:text-5xl"):
                    self.assertContains(page, text)
        self.assertContains(self.client.get(reverse("events:event_detail", args=[self.event.slug])), "Cancelled")

    def test_list_pages_share_the_card(self):
        activities = self.client.get(reverse("activities:activity_list"))
        events = self.client.get(reverse("events:event_list"))
        for page, url in ((activities, reverse("activities:activity_detail", args=[self.activity.slug])),
                          (events, reverse("events:event_detail", args=[self.event.slug]))):
            self.assertContains(page, "sbl-card sbl-card-hover flex h-full flex-col overflow-hidden")
            self.assertContains(page, url)
        self.assertContains(activities, "Every year · September")
        self.assertNotContains(activities, "POIs")  # the old country-page leftovers are gone
        self.assertContains(events, "Cancelled")

    def test_activity_list_filters_by_country(self):
        url = reverse("activities:activity_list")
        self.assertContains(self.client.get(url, {"country": "germany"}), "Oktoberfest")
        self.assertNotContains(self.client.get(url, {"country": "france"}), "Oktoberfest")
